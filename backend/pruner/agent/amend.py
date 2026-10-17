"""The amend-objectives agent: after the objectives change, decide where exploration should
restart from.

It walks the tree layer by layer from the root. For every node in the current layer it re-rates
that node's live children (not parked or failed) against the amended objectives, siblings
together in one call to the pre-scorer (the weak model), and writes the new pre-scores onto them.
Then, per node:
  - every child is low (overall < cfg.backtrack_below): the direction no longer fits below this
    node, so it calls the fork tool there and does not look further down that subtree;
  - otherwise it keeps walking down the children that are not low.
So it backtracks only when ALL branches under a node are low, which keeps it loose: progress that
still partly serves the objectives is never thrown away. If the root's children are all low, it
forks at the root (the user changed direction completely).

Tools:
  - rate_layer: the pre-scorer call above.
  - fork: stores a ForkRequest at that node (RunStore.append_fork). Forking the tree itself is not
    built yet, so this only records where it should happen.
The walk and the backtracking rule are code, not an LLM choosing tool calls: the LLM wrapper has
no function calling yet, and code guarantees the "all branches must be low" rule. The same two
operations are exposed as Tool objects (tools_for) for an LLM-driven version later.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from pruner.agent.tools import Tool
from pruner.core.config import Config, get_config
from pruner.core.models import ForkRequest, Node, Run
from pruner.pruning.prescorer import PreScored, PreScorer
from pruner.pruning.scale import to_ten
from pruner.runs.store import RunStore

DEAD = ("parked", "failed")  # not live branches; parked ones are handled by PreScorer.rescore


@dataclass
class AmendResult:
    rated: list[PreScored] = field(default_factory=list)  # every node that was re-rated
    forks: list[ForkRequest] = field(default_factory=list)


class AmendObjectivesAgent:
    def __init__(self, scorer: PreScorer, store: RunStore, cfg: Config | None = None) -> None:
        self.scorer, self.store = scorer, store
        self.cfg = cfg or get_config()

    # ---- the two tools

    async def rate_layer(self, run: Run, siblings: Sequence[Node]) -> list[PreScored]:
        """Re-rate sibling nodes against the run's current objectives and write the new
        pre-scores (and the scorer tokens) onto them."""
        scored = await self.scorer.rate_for_amendment(
            siblings, question=run.question, objectives=run.objectives,
            people=run.vault_people, instructions=run.instructions,
            directives=run.directives)
        for node, s in zip(siblings, scored, strict=True):
            node.pre_score = s.pre_score
            node.tokens.scorer += s.tokens.total
        return scored

    def fork(self, run: Run, node: Node, reason: str) -> ForkRequest:
        """Record that exploration should restart from `node`. Forking is not built yet."""
        request = ForkRequest(run_id=run.id, node_id=node.id, reason=reason,
                              objective_ids=[o.id for o in run.objectives])
        self.store.append_fork(request)
        return request

    def tools_for(self, run: Run, nodes: Sequence[Node]) -> tuple[Tool, Tool]:
        """The same operations as Tool objects, for an LLM-driven agent later."""
        by_id = {n.id: n for n in nodes}

        async def rate(node_ids: list[str]) -> str:
            scored = await self.rate_layer(run, [by_id[i] for i in node_ids])
            return json.dumps({s.node_id: to_ten(s.pre_score.overall) for s in scored})

        async def fork(node_id: str, reason: str) -> str:
            return self.fork(run, by_id[node_id], reason).id

        return (
            Tool("rate_layer", "Re-rate sibling nodes against the amended objectives (1-10).",
                 {"type": "object", "properties": {"node_ids": {"type": "array",
                                                               "items": {"type": "string"}}},
                  "required": ["node_ids"]}, rate),
            Tool("fork", "Restart exploration from this node (not built yet: records it).",
                 {"type": "object", "properties": {"node_id": {"type": "string"},
                                                   "reason": {"type": "string"}},
                  "required": ["node_id", "reason"]}, fork),
        )

    # ---- the walk

    async def run(self, run: Run, nodes: Sequence[Node],
                  checkpoint: Callable[[], Awaitable[None]] | None = None) -> AmendResult:
        """Walk the tree. `checkpoint`, if given, is awaited before each layer is rated, so a
        paused run holds between layers (the calls of a layer already started still finish)."""
        children: dict[str, list[Node]] = defaultdict(list)
        for n in nodes:
            if n.parent_id is not None:
                children[n.parent_id].append(n)
        result = AmendResult()
        frontier = [n for n in nodes if n.parent_id is None]
        for _ in range(self.cfg.max_depth + 1):  # a tree never goes deeper than the cap
            if checkpoint is not None:
                await checkpoint()
            groups = [(p, kids) for p in frontier
                      if (kids := [c for c in children[p.id] if c.status not in DEAD])]
            if not groups:
                break
            layer = await asyncio.gather(*(self.rate_layer(run, kids) for _, kids in groups))
            frontier = []
            for (parent, kids), scored in zip(groups, layer, strict=True):
                result.rated.extend(scored)
                low = [s.zone == "park" for s in scored]
                if all(low):
                    best = max(to_ten(s.pre_score.overall) for s in scored)
                    result.forks.append(self.fork(run, parent, (
                        f"All {len(kids)} branches under this step scored low against the "
                        f"amended objectives (best {best:.1f}/10, below "
                        f"{self.cfg.backtrack_below:.1f}).")))
                else:
                    frontier += [k for k, is_low in zip(kids, low, strict=True) if not is_low]
        return result
