"""Pre-scoring: screen candidate experiments before they run.

For one set of sibling candidates (the agent's proposals from one parent):
  1. Duplicate check (embeddings, no LLM): flag candidates that nearly repeat earlier work, a
     failed-log entry, or an earlier sibling.
  2. Vault search: the chosen people's items close to each candidate (nothing if nothing is
     close: cfg.similarity_threshold, at most cfg.search_top_k).
  3. One judge call (fast model) ranks the siblings against each other: reason first, then
     1..10 plausible / relevant / novel (tenths, stored as 0..1 by scale.to_unit), citing
     vault notes.
  4. Zones from the average (overall) on the 1..10 scale: below cfg.pre_score_min -> park
     (verdict park, restorable); below cfg.run_score_min -> borderline (verdict keep; the agent
     may look ahead or ask a human); otherwise run. The UI can show low / medium / high by
     translating the number.

rate_for_directive() is the steering re-rate: after an instruction or a chip toggle, one batched
call (30 nodes per call) rates how relevant every node is now and names a result key the
instruction needs that a node did not measure (applied by orchestrator/steering.py).

The prescorer only judges: the agent loop decides what to do with the zones, usually by
calling apply() on each node and then running the survivors. The judge never sees results; it rates how promising the next step is.

Every vault note shown to the judge counts as one retrieval (VaultStore.record_retrieval).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM, TokenCount
from pruner.core.models import DeadEnd, Decision, Directive, Instruction, Node, Objective, PreScore
from pruner.pruning.scale import to_ten, to_unit
from pruner.vault.store import VaultStore, one_line, unit_vectors

log = logging.getLogger(__name__)

Zone = Literal["park", "borderline", "run"]
DUPLICATE_THRESHOLD = 0.9  # cosine similarity; tune on real hypotheses (move to config if kept)


class CandidateRating(BaseModel):
    """What the judge returns per candidate. Field order matters: reason comes first."""

    node_id: str
    reason: str
    plausible: float = Field(ge=0, le=10)  # 1 to 10 scale, tenths allowed
    relevant: float = Field(ge=0, le=10)
    novel: float = Field(ge=0, le=10)
    vault_items_used: list[str] = Field(default_factory=list)


class PreScoreBatch(BaseModel):
    ratings: list[CandidateRating] = Field(default_factory=list)


class SteerRating(BaseModel):
    """The steering re-rate of one node. Field order matters: reason comes first."""

    node_id: str
    reason: str
    relevant: float = Field(ge=0, le=10)  # 1 to 10, tenths allowed
    metric_needed: str = ""  # a result key the instruction needs measured, if any


class SteerBatch(BaseModel):
    ratings: list[SteerRating] = Field(default_factory=list)


STEER_CHUNK = 30  # nodes per steering re-rate call


@dataclass
class SteerScored:
    node_id: str
    relevant: float  # 0..1
    reason: str
    metric_needed: str
    tokens: TokenCount = field(default_factory=TokenCount)


def steer_block(node: Node) -> str:
    """One node as the steering re-rate sees it: status, family, summary, verdict, measured."""
    head = f"Node {node.id} ({node.status}, family {node.family or '-'}"
    if node.verdict:
        head += f", {node.verdict}"
    lines = [f"{head}): {node.summary or node.description}"]
    if node.experiment is not None:
        keys = ", ".join(sorted(node.experiment.metrics)) or "(none)"
        lines.append(f"Measured keys: {keys}")
        if node.synthesis is not None:
            lines.append(f"What it found: {one_line(node.synthesis.measured)[:300]}")
    else:
        lines.append("Not run yet.")
    return "\n".join(lines)


Change = Literal["unparked", "parked", "unchanged"]


@dataclass
class Rescored:
    node_id: str
    before: str  # the node's status before the rescore ("parked" or "pending")
    scored: PreScored
    change: Change


@dataclass
class PreScored:
    node_id: str
    pre_score: PreScore
    decision: Decision
    zone: Zone
    retrieved: list[str] = field(default_factory=list)  # vault ids shown to the judge
    duplicate_of: str | None = None  # the earlier text this nearly repeats, if any
    tokens: TokenCount = field(default_factory=TokenCount)  # this node's share of the call


class PreScorer:
    def __init__(self, vault: VaultStore, llm: LLM | None = None,
                 cfg: Config | None = None) -> None:
        self.cfg = cfg or get_config()
        self.vault = vault
        self.llm = llm or vault.llm

    async def find_duplicates(self, nodes: Sequence[Node],
                              earlier: Sequence[str]) -> dict[str, str]:
        """node id -> the earlier text it nearly repeats. `earlier` holds the descriptions of
        earlier experiments and failed-log entries; earlier siblings are checked too."""
        texts = [n.full_text() for n in nodes]
        vectors = np.array(await self.llm.embed([*texts, *earlier], task="SEMANTIC_SIMILARITY",
                                                purpose="scorer_embed"), dtype=np.float32)
        sims = unit_vectors(vectors[: len(nodes)]) @ unit_vectors(vectors).T
        known = [*texts, *earlier]
        found: dict[str, str] = {}
        for i, node in enumerate(nodes):
            for j in range(len(known)):
                if j == i or (j < len(nodes) and j > i):  # later siblings are not "earlier"
                    continue
                if sims[i, j] >= DUPLICATE_THRESHOLD:
                    found[node.id] = known[j]
                    break
        return found

    async def score_siblings(self, nodes: Sequence[Node], *, question: str,
                             objectives: list[Objective], people: Sequence[str],
                             parent: Node | None = None, dead_ends: Sequence[DeadEnd] = (),
                             earlier: Sequence[str] = (),
                             instructions: Sequence[Instruction] = (),
                             directives: Sequence[Directive | str] = ()) -> list[PreScored]:
        """Rate sibling candidates against each other in a single judge call. Results are in
        the same order as `nodes`."""
        if not nodes:
            return []
        duplicates = await self.find_duplicates(nodes, earlier)
        hits = await self._search(nodes, people)

        blocks = []
        for node, node_hits in zip(nodes, hits, strict=True):
            lines = [f"Candidate {node.id} ({node.type}): {node.full_text()}"]
            if node.id in duplicates:
                lines.append(f"Possible repeat of earlier work: {duplicates[node.id]}")
            blocks.append("\n".join([*lines, *self._vault_lines(people, node_hits)]))

        prompt = prompts.render(
            "pre_score",
            question=question,
            instructions=prompts.render_instructions(instructions, directives),
            objectives=prompts.render_objectives(objectives),
            parent=parent.full_text() if parent else "(this is the first step)",
            dead_ends=prompts.render_dead_ends(dead_ends),
            candidates="\n\n".join(blocks),
        )
        gen = await self.llm.generate(PreScoreBatch, prompt, model=self.cfg.fast_model,
                                      purpose="scorer")
        return self._results(
            nodes, hits, gen,
            park_below=self.cfg.pre_score_min, duplicates=duplicates)

    async def rescore(self, nodes: Sequence[Node], *, question: str,
                      objectives: list[Objective], people: Sequence[str],
                      instructions: Sequence[Instruction] = (),
                      directives: Sequence[Directive | str] = ()) -> list[Rescored]:
        """Re-judge the tree after the user amends the question or instructions.

        Looks at every parked node and every node still waiting to run (nodes a human decided,
        and nodes that already ran and were kept, are left alone) and judges each by its topic
        against the new instructions, in one call. Unparking is lenient: a branch ends parked
        only if its overall score is under cfg.rescore_park_below, so anything fairly close to
        what is now asked for comes back, and clearly less useful pending branches are parked.
        Dead ends are not shown: a parked branch's old reason is, so the judge can see whether
        the new instructions overturn it.
        """
        eligible = [n for n in nodes
                    if n.status in ("parked", "pending") and n.decided_by != "human"]
        if not eligible:
            return []
        hits = await self._search(eligible, people)

        blocks = []
        for node, node_hits in zip(eligible, hits, strict=True):
            head = f"Candidate {node.id} ({node.type}, currently {node.status})"
            lines = [f"{head}: {node.full_text()}"]
            if node.decision:
                lines.append(f"Earlier decision ({node.decision.verdict}): {node.decision.reason}")
            blocks.append("\n".join([*lines, *self._vault_lines(people, node_hits)]))

        prompt = prompts.render(
            "rescore",
            question=question,
            instructions=prompts.render_instructions(instructions, directives),
            objectives=prompts.render_objectives(objectives),
            candidates="\n\n".join(blocks),
        )
        gen = await self.llm.generate(PreScoreBatch, prompt, model=self.cfg.fast_model,
                                      purpose="scorer")
        scored = self._results(eligible, hits, gen, park_below=self.cfg.rescore_park_below)
        out = []
        for node, result in zip(eligible, scored, strict=True):
            now_parked = result.zone == "park"
            was_parked = node.status == "parked"
            change: Change = ("unparked" if was_parked and not now_parked
                              else "parked" if now_parked and not was_parked else "unchanged")
            out.append(Rescored(node.id, node.status, result, change))
        return out

    async def rate_for_amendment(self, nodes: Sequence[Node], *, question: str,
                                 objectives: list[Objective], people: Sequence[str],
                                 instructions: Sequence[Instruction] = (),
                                 directives: Sequence[Directive | str] = ()) -> list[PreScored]:
        """Re-rate sibling branches (any status, including ones that already ran) against
        amended objectives, in one call. The prompt is loose on purpose. A result in the "park"
        zone here means "low": overall under cfg.backtrack_below. Nothing is written to nodes."""
        if not nodes:
            return []
        hits = await self._search(nodes, people)
        blocks = []
        for node, node_hits in zip(nodes, hits, strict=True):
            lines = [f"Candidate {node.id} ({node.type}, {node.status}): {node.full_text()}"]
            if node.result:
                lines.append(f"What it found: {one_line(node.result)[:300]}")
            blocks.append("\n".join([*lines, *self._vault_lines(people, node_hits)]))
        prompt = prompts.render(
            "amend_rate",
            question=question,
            instructions=prompts.render_instructions(instructions, directives),
            objectives=prompts.render_objectives(objectives),
            candidates="\n\n".join(blocks),
        )
        gen = await self.llm.generate(PreScoreBatch, prompt, model=self.cfg.fast_model,
                                      purpose="scorer")
        return self._results(nodes, hits, gen, park_below=self.cfg.backtrack_below)

    async def rate_for_directive(self, nodes: Sequence[Node], *, question: str,
                                 objectives: list[Objective], change: str,
                                 instructions: Sequence[Instruction] = (),
                                 directives: Sequence[Directive | str] = (),
                                 findings: str = "(none)", measured: str = "(none)",
                                 chunk: int = STEER_CHUNK) -> list[SteerScored]:
        """The steering re-rate: how relevant each node (pending, parked or finished) is to the
        run now that `change` happened (an instruction was added or a chip turned on/off), and a
        result key the instruction needs that the node's experiment did not measure. One call per
        `chunk` nodes, no vault search, no experiment re-run. Nodes the judge skipped are left
        out of the result. Nothing is written to nodes (see orchestrator/steering.py)."""
        out: list[SteerScored] = []
        for start in range(0, len(nodes), chunk):
            part = list(nodes[start:start + chunk])
            prompt = prompts.render(
                "steer_rate", question=question, change=change,
                instructions=prompts.render_instructions(instructions, directives),
                objectives=prompts.render_objectives(objectives), findings=findings,
                measured=measured, nodes="\n\n".join(steer_block(n) for n in part))
            gen = await self.llm.generate(SteerBatch, prompt, model=self.cfg.fast_model,
                                          purpose="scorer")
            judged = {r.node_id: r for r in gen.value.ratings}
            share = TokenCount(input=gen.tokens.input // len(part),
                               output=gen.tokens.output // len(part), calls=gen.tokens.calls)
            for node in part:
                r = judged.get(node.id)
                if r is None:
                    log.warning("steering re-rate gave no score for %s", node.id)
                    continue
                out.append(SteerScored(node.id, to_unit(r.relevant), one_line(r.reason),
                                       r.metric_needed.strip(), share))
        return out

    # ---- shared pieces

    async def _search(self, nodes: Sequence[Node], people: Sequence[str]) -> list[list]:
        queries = await self.llm.embed([n.full_text() for n in nodes], task="RETRIEVAL_QUERY",
                                       purpose="scorer_embed")
        hits = [self.vault.nearest(q, k=self.cfg.search_top_k,
                                   threshold=self.cfg.similarity_threshold, people=people)
                for q in queries]
        self.vault.record_retrieval(i.id for node_hits in hits for i, _ in node_hits)
        return hits

    @staticmethod
    def _vault_lines(people: Sequence[str], node_hits: list) -> list[str]:
        header = f"Vault items ({', '.join(people) or 'nobody'}) close to this candidate:"
        return [header, *(f"{i.id} ({i.kind}, {i.person}): {i.title}. {i.summary}"
                          for i, _ in node_hits)] if node_hits else [header, "(nothing close)"]

    def _results(self, nodes: Sequence[Node], hits: list[list], gen, *, park_below: float,
                 duplicates: dict[str, str] | None = None) -> list[PreScored]:
        judged = {r.node_id: r for r in gen.value.ratings}
        share = TokenCount(input=gen.tokens.input // len(nodes),
                           output=gen.tokens.output // len(nodes), calls=gen.tokens.calls)
        results = []
        for node, node_hits in zip(nodes, hits, strict=True):
            shown = {i.id for i, _ in node_hits}
            r = judged.get(node.id)
            if r is None:  # lean permissive: an unjudged candidate goes to the borderline zone
                log.warning("judge gave no score for %s; treating as borderline", node.id)
                mid = (park_below + self.cfg.run_score_min) / 2
                r = CandidateRating(node_id=node.id, reason="The judge gave no score.",
                                    plausible=mid, relevant=mid, novel=mid)
            pre = PreScore(plausible=to_unit(r.plausible), relevant=to_unit(r.relevant),
                           novel=to_unit(r.novel))
            overall = to_ten(pre.overall)
            zone: Zone = ("park" if overall < park_below
                          else "borderline" if overall < self.cfg.run_score_min else "run")
            results.append(PreScored(
                node_id=node.id,
                pre_score=pre,
                decision=Decision(
                    verdict="park" if zone == "park" else "keep", stage="pre",
                    reason=one_line(r.reason),
                    vault_items_used=[i for i in dict.fromkeys(r.vault_items_used) if i in shown]),
                zone=zone, retrieved=[i.id for i, _ in node_hits],
                duplicate_of=(duplicates or {}).get(node.id), tokens=share,
            ))
        return results

    async def score(self, node: Node, **kwargs) -> PreScored:
        """Score a single candidate (no siblings to compare against)."""
        [result] = await self.score_siblings([node], **kwargs)
        return result


def apply(node: Node, result: PreScored) -> Node:
    """Write a result onto its node: scores, decision, scorer tokens, and status if parked."""
    node.pre_score = result.pre_score
    node.decision = result.decision
    node.decided_by = "agent"
    node.tokens.scorer += result.tokens.total
    if result.zone == "park":
        node.status = "parked"
    return node


def apply_rescore(node: Node, result: Rescored) -> Node:
    """Write a rescore onto its node. Unparked nodes that already ran go back to done, the
    rest to pending; newly parked ones become parked. Unchanged nodes still get fresh scores."""
    apply(node, result.scored)
    if result.change == "unparked":
        node.status = "done" if node.result is not None else "pending"
    return node
