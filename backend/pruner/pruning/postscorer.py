"""Post-scoring: judge an executed node's result.

For one node that has run (node.result is set):
  1. Vault search: the chosen people's items close to the experiment and its result (nothing
     if nothing is close: cfg.similarity_threshold, at most cfg.search_top_k).
  2. One judge call (fast model): reason first, a 1..10 post_score (tenths, converted to 0..1),
     and which objectives the result advances, against the baseline and the user's
     instructions.
  3. The node is kept if its 1..10 post_score >= cfg.post_score_min or it advances any objective;
     otherwise it is parked (verdict park, restorable).

Like the prescorer, this only judges: the agent loop decides what to do with the result, usually
by calling apply() on the node. The judge interprets; it does not choose the next step.

TODO(agent loop): emit VaultRetrieved for PostScored.retrieved and bump retrieval_count.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM, TokenCount
from pruner.core.models import DeadEnd, Decision, Directive, Instruction, Node, Objective
from pruner.pruning.scale import to_unit
from pruner.vault.store import VaultStore, one_line

log = logging.getLogger(__name__)


class PostScoreOutput(BaseModel):
    """What the judge returns. Field order matters: reason comes first."""

    reason: str
    post_score: float = Field(ge=0, le=10)  # 1 to 10 scale, tenths allowed
    criteria_progress: list[str] = Field(default_factory=list)
    vault_items_used: list[str] = Field(default_factory=list)


@dataclass
class PostScored:
    node_id: str
    post_score: float
    criteria_progress: list[str]
    decision: Decision
    retrieved: list[str] = field(default_factory=list)  # vault ids shown to the judge
    tokens: TokenCount = field(default_factory=TokenCount)


class PostScorer:
    def __init__(self, vault: VaultStore, llm: LLM | None = None,
                 cfg: Config | None = None) -> None:
        self.cfg = cfg or get_config()
        self.vault = vault
        self.llm = llm or vault.llm

    async def score(self, node: Node, *, question: str, objectives: list[Objective],
                    people: Sequence[str], baseline: str = "", dead_ends: Sequence[DeadEnd] = (),
                    instructions: Sequence[Instruction] = (),
                    directives: Sequence[Directive | str] = ()) -> PostScored:
        if node.result is None:
            raise ValueError(f"node {node.id} has no result to score")
        [query] = await self.llm.embed([f"{node.description}\n{node.result}"],
                                       task="RETRIEVAL_QUERY", purpose="scorer_embed")
        hits = self.vault.nearest(query, k=self.cfg.search_top_k,
                                  threshold=self.cfg.similarity_threshold, people=people)
        shown = {i.id for i, _ in hits}

        prompt = prompts.render(
            "post_score",
            question=question,
            instructions=prompts.render_instructions(instructions, directives),
            objectives=prompts.render_objectives(objectives),
            baseline=baseline or "(no baseline recorded)",
            node_type=node.type,
            description=node.description,
            result=node.result,
            people=", ".join(people) or "nobody",
            vault_items="\n".join(f"{i.id} ({i.kind}, {i.person}): {i.title}. {i.summary}"
                                  for i, _ in hits) or "(nothing close)",
            dead_ends=prompts.render_dead_ends(dead_ends),
        )
        gen = await self.llm.generate(PostScoreOutput, prompt, model=self.cfg.fast_model,
                                      purpose="scorer")
        out = gen.value

        valid = {c.id for c in objectives}
        progress = [c for c in dict.fromkeys(out.criteria_progress) if c in valid]
        post_score = to_unit(out.post_score)
        keep = round(out.post_score, 1) >= self.cfg.post_score_min or bool(progress)
        return PostScored(
            node_id=node.id, post_score=post_score, criteria_progress=progress,
            decision=Decision(
                verdict="keep" if keep else "park", stage="post", reason=one_line(out.reason),
                vault_items_used=[i for i in dict.fromkeys(out.vault_items_used) if i in shown]),
            retrieved=[i.id for i, _ in hits], tokens=gen.tokens,
        )


def apply(node: Node, result: PostScored) -> Node:
    """Write a result onto its node: score, progress, decision, scorer tokens, and status."""
    node.post_score = result.post_score
    node.criteria_progress = result.criteria_progress
    node.decision = result.decision
    node.decided_by = "agent"
    node.tokens.scorer += result.tokens.total
    node.status = "done" if result.decision.verdict == "keep" else "parked"
    return node
