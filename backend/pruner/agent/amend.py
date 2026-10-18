"""The amend-objectives agent: after the objectives are amended, suggest where exploration should
restart from (FORK_PLAN.md).

It scores nothing itself. The steering re-rate that runs right after an amendment
(Orchestrator.steer, one batched call) has just written every node's relevance to the amended
objectives (Node.directive_score), and the agent reads those, so the card and the queue show the
same numbers. From them it picks the fork point F (orchestrator/fork.py choose_fork_point):
  walk down from the root through nodes scoring at least cfg.fork_relevant_at (7/10); F is the
  deepest node reached, or the lowest common ancestor of several qualifying branches, or the
  root (the baseline) when nothing qualifies.
The result is a ForkRequest a person confirms or dismisses (never applied by itself); it is None
when a fork there would park nothing. The choice is code, not an LLM picking tool calls, so the
rule holds exactly; the operations are also exposed as Tool objects (tools_for).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pruner.agent.tools import Tool
from pruner.core.config import Config, get_config
from pruner.core.models import ForkRequest, Node, Run
from pruner.orchestrator import fork
from pruner.pruning.prescorer import PreScored, PreScorer
from pruner.pruning.scale import to_ten
from pruner.runs.store import RunStore


class AmendObjectivesAgent:
    def __init__(self, scorer: PreScorer, store: RunStore, cfg: Config | None = None) -> None:
        self.scorer, self.store = scorer, store
        self.cfg = cfg or get_config()

    async def rate_layer(self, run: Run, siblings: Sequence[Node]) -> list[PreScored]:
        """Re-rate sibling nodes against the run's current objectives (pre-score scale) and
        write the new pre-scores onto them. Kept as a tool; the fork itself uses the steering
        re-rate's directive scores."""
        scored = await self.scorer.rate_for_amendment(
            siblings, question=run.question, objectives=run.objectives,
            people=run.vault_people, instructions=run.instructions,
            directives=run.directives)
        for node, s in zip(siblings, scored, strict=True):
            node.pre_score = s.pre_score
            node.tokens.scorer += s.tokens.total
        return scored

    def propose_fork(self, run: Run, nodes: Sequence[Node]) -> ForkRequest | None:
        """The fork to suggest after amended objectives (None if it would park nothing)."""
        if not any(n.parent_id is None for n in nodes):
            return None
        return fork.plan(run, nodes, self.cfg)

    def tools_for(self, run: Run, nodes: Sequence[Node]) -> tuple[Tool, Tool]:
        """The same operations as Tool objects, for an LLM-driven agent later."""
        by_id = {n.id: n for n in nodes}

        async def rate(node_ids: list[str]) -> str:
            scored = await self.rate_layer(run, [by_id[i] for i in node_ids])
            return json.dumps({s.node_id: to_ten(s.pre_score.overall) for s in scored})

        async def suggest_fork() -> str:
            request = self.propose_fork(run, nodes)
            return json.dumps(request.model_dump() if request else {"fork": None})

        return (
            Tool("rate_layer", "Re-rate sibling nodes against the amended objectives (1-10).",
                 {"type": "object", "properties": {"node_ids": {"type": "array",
                                                               "items": {"type": "string"}}},
                  "required": ["node_ids"]}, rate),
            Tool("suggest_fork", "Where exploration should restart for the amended objectives: "
                                 "the deepest node still scoring 7/10 or more on its path (a "
                                 "person confirms it).",
                 {"type": "object", "properties": {}}, suggest_fork),
        )
