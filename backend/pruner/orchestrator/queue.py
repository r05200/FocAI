"""Which waiting node runs next (pure, no LLM).

Candidates are the pending nodes (validated, pre-scored, not parked) whose parent is not
closed. Each gets a priority in 0..1:
    0.4 x its pre-score
  + 0.3 x its lineage (the parent's post-score if the parent was supported, else 0.5)
  + 0.2 x its latest directive score (0.5 if no directive rated it)
  + 0.1 x its novelty
  - 0.05 x its depth
  + 0.2 if a person kept or restored it
Families are kept alive: a node loses 0.15 for every experiment its family has run beyond the
least-run family that still has candidates, so one promising family cannot starve the others.
Ties go to the older node. A confirmed suggestion (focus) wins once.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pruner.core.models import Node

FAMILY_PENALTY = 0.15


def _order(node: Node) -> int:
    m = re.fullmatch(r"n(\d+)", node.id)
    return int(m.group(1)) if m else 10**9


def priority(node: Node, by_id: dict[str, Node]) -> float:
    pre = node.pre_score.overall if node.pre_score else 0.5
    novel = node.pre_score.novel if node.pre_score else 0.5
    parent = by_id.get(node.parent_id) if node.parent_id else None
    lineage = (parent.post_score if parent and parent.verdict == "supported"
               and parent.post_score is not None else 0.5)
    directive = 0.5  # directive scores arrive with steering (M4)
    human = 0.2 if node.decided_by == "human" else 0.0
    return round(0.4 * pre + 0.3 * lineage + 0.2 * directive + 0.1 * novel
                 - 0.05 * node.depth + human, 4)


def candidates(nodes: Sequence[Node]) -> list[Node]:
    by_id = {n.id: n for n in nodes}
    return [n for n in nodes if n.status == "pending" and n.phase == "hypothesis"
            and not (n.parent_id and by_id.get(n.parent_id) and by_id[n.parent_id].closed)]


def select_next(nodes: Sequence[Node], focus: str | None = None) -> Node | None:
    """The node to run next (its `priority` and its rivals' are written back), or None."""
    pool = candidates(nodes)
    if not pool:
        return None
    by_id = {n.id: n for n in nodes}
    if focus is not None and focus in {n.id for n in pool}:
        return by_id[focus]
    runs: dict[str, int] = {}
    for n in nodes:
        if n.family and n.experiment is not None:
            runs[n.family] = runs.get(n.family, 0) + 1
    live = {n.family or "" for n in pool}
    least = min(runs.get(f, 0) for f in live)
    best, best_score = None, float("-inf")
    for n in sorted(pool, key=_order):
        score = priority(n, by_id) - FAMILY_PENALTY * (runs.get(n.family or "", 0) - least)
        n.priority = round(score, 4)
        if score > best_score:
            best, best_score = n, score
    return best
