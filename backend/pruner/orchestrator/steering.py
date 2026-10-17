"""Steering: what an instruction, or a chip turned on or off, changes in the tree. Nothing is
re-run.

After the objectives are amended, one batched re-rate (PreScorer.rate_for_directive, the weak
model, up to 30 nodes per call) scores every waiting, parked and finished node (not the baseline)
for relevance to the run now. apply_rerate() writes each score:
  - every node: directive_score and directive_reason (the queue's directive term), plus
    needs_remeasure and missing_metrics when the instruction needs a result key the node's
    experiment did not measure;
  - a person's decisions are never overridden: a human-decided node only gets the score;
  - a waiting node now below cfg.rescore_park_below is parked (restorable);
  - a node the agent parked before it ran (not as a repeat) that now scores at or above that
    threshold goes back to the queue;
  - finished nodes keep their status (a low score only moves them down).
suggest() then offers up to 3 places to continue from, from different families, without an LLM:
the amend agent's fork requests first, then the relevant nodes ranked by 0.6 x directive score +
0.4 x queue priority. Confirming one (RunManager.resolve_suggestion) runs that node next, restores
it, or queues a Job: new hypotheses from it, or an experiment that adds the missing measurement.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pruner.core.config import Config
from pruner.core.events import NodeChange
from pruner.core.models import Decision, ForkRequest, Node, Run, Suggestion, SuggestionAction
from pruner.orchestrator.actions import room_under
from pruner.orchestrator.queue import blocked
from pruner.pruning.prescorer import SteerScored
from pruner.pruning.scale import to_ten

REPEAT_PREFIX = "Repeats earlier work"  # the proposer's reason for parking a repeat
SUGGESTIONS = 3


@dataclass
class Job:
    """An expansion a person asked for (a confirmed suggestion or a restore), run before the next
    experiment."""

    node_id: str
    mode: str  # a proposer mode (orchestrator/proposer.py MODE_BRIEFS)
    brief: str = ""
    count: int = 2


def rerate_targets(nodes: Sequence[Node]) -> list[Node]:
    return [n for n in nodes if n.parent_id is not None
            and n.status in ("pending", "parked", "done")]


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def metric_missing(node: Node, metric: str) -> bool:
    """True if `metric` is named and none of the node's measured keys looks like it."""
    want = _key(metric)
    if not want or node.experiment is None or node.experiment.error:
        return False
    keys = [_key(k) for k in node.experiment.metrics]
    return not any(k and (want in k or k in want) for k in keys)


def apply_rerate(node: Node, scored: SteerScored, cfg: Config) -> NodeChange:
    """Write one re-rate onto its node; the change to announce ("parked", "restored", "scored")."""
    node.directive_score = scored.relevant
    node.directive_reason = scored.reason
    node.tokens.scorer += scored.tokens.total
    if node.experiment is not None:
        missing = metric_missing(node, scored.metric_needed)
        node.needs_remeasure = missing
        node.missing_metrics = [scored.metric_needed] if missing else []
    if node.decided_by == "human":
        return "scored"
    relevant = to_ten(scored.relevant) >= cfg.rescore_park_below
    if node.status == "pending" and not relevant:
        node.status = "parked"
        node.decided_by = "agent"
        node.decision = Decision(verdict="park", stage="pre",
                                 reason=f"Off the current direction: {scored.reason}")
        return "parked"
    if (node.status == "parked" and relevant and node.experiment is None
            and not (node.decision and node.decision.reason.startswith(REPEAT_PREFIX))):
        node.status = "pending"
        node.decided_by = "agent"
        node.decision = Decision(verdict="keep", stage="pre",
                                 reason=f"Back in line with the current direction: "
                                        f"{scored.reason}")
        return "restored"
    return "scored"


def _option(run: Run, nodes: Sequence[Node], node: Node,
            by_id: dict[str, Node]) -> SuggestionAction | None:
    if node.status == "pending":
        return None if blocked(node, by_id) else "run"
    if node.status == "parked":
        # agent parks that became relevant are already back; a person's park is only suggested
        return "restore" if node.decided_by == "human" else None
    if node.status == "done" and room_under(run, nodes, node) > 0:
        if node.needs_remeasure:
            return "remeasure"
        if node.verdict == "supported":
            return "expand"
    return None


def suggest(run: Run, nodes: Sequence[Node], cfg: Config, *, instruction_id: str | None,
            forks: Sequence[ForkRequest] = (), limit: int = SUGGESTIONS) -> list[Suggestion]:
    by_id = {n.id: n for n in nodes}
    out: list[Suggestion] = []
    families: set[str] = set()

    def add(node: Node, action: SuggestionAction, reason: str, score: float,
            source: str) -> None:
        out.append(Suggestion(run_id=run.id, node_id=node.id, action=action, reason=reason,
                              family=node.family, score=round(min(1.0, max(0.0, score)), 4),
                              source=source, instruction_id=instruction_id))  # type: ignore[arg-type]
        families.add(node.family or node.id)

    for fork in forks:
        node = by_id.get(fork.node_id)
        if (node is not None and len(out) < limit and room_under(run, nodes, node) > 0
                and all(s.node_id != node.id for s in out)):
            add(node, "expand", fork.reason, node.directive_score or 0.0, "fork")

    ranked = []
    for node in nodes:
        if node.parent_id is None or node.directive_score is None:
            continue
        if to_ten(node.directive_score) < cfg.rescore_park_below:
            continue
        action = _option(run, nodes, node, by_id)
        if action is None:
            continue
        priority = node.priority if node.priority is not None else 0.5
        ranked.append((0.6 * node.directive_score + 0.4 * min(1.0, max(0.0, priority)),
                       node, action))
    for score, node, action in sorted(ranked, key=lambda r: -r[0]):
        if len(out) >= limit:
            break
        if (node.family or node.id) in families:
            continue
        add(node, action, node.directive_reason, score, "steer")
    return out


def job_for(suggestion: Suggestion, node: Node) -> Job | None:
    """The expansion a confirmed suggestion asks for (None for run and restore)."""
    if suggestion.action == "expand":
        mode = "new_hypothesis" if suggestion.source == "fork" else "more_experiments"
        return Job(node.id, mode, f"A person chose to continue here: {suggestion.reason}")
    if suggestion.action == "remeasure":
        wanted = ", ".join(node.missing_metrics) or "the quantity the instruction asks about"
        return Job(node.id, "diagnose",
                   f"The user's latest instruction needs {wanted}, which this experiment did "
                   f"not measure. Keep this node's change and add that measurement to the "
                   f"command's result.", count=1)
    return None
