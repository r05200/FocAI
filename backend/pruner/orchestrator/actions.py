"""The next-action menu and the budget (pure functions, no LLM).

After synthesis the agent picks one action; plan_action() checks it against the budget and turns
it into an expansion (which node to propose from, in which mode, how many) or nothing:

  more_experiments  refine or vary this hypothesis: children of this node, same family (1-2)
  new_hypothesis    a different family: a sibling of this node (children of its parent)
  diagnose          explain a surprising or failed result: one child of this node
  combine           merge this node's change with other supported ones (targets): one child
  resolve           tell apart a result and a note/finding that contradicts it: one child
  transfer          apply this node's supported change elsewhere: one child of the target node
                    (or of this node)
  stop              close this branch: no children from this node (the run itself ends only on
                    budget, an empty queue, or every objective covered)

Budget: experiments left (pending nodes already reserve one each), the depth cap, and the
branching cap of the parent. A blocked action falls back: more_experiments / diagnose / combine /
resolve / transfer -> new_hypothesis at the parent -> stop; every fallback is explained.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pruner.core.models import Node, Run

NODE_ACTIONS = ("more_experiments", "diagnose", "combine", "resolve", "transfer")


def experiments_run(nodes: Sequence[Node]) -> int:
    return sum(1 for n in nodes if n.experiment is not None)


def pending(nodes: Sequence[Node]) -> int:
    return sum(1 for n in nodes if n.status == "pending")


def experiments_left(run: Run, nodes: Sequence[Node]) -> int:
    """Experiments the budget still allows, minus those already waiting in the queue."""
    return run.caps.node_budget - experiments_run(nodes) - pending(nodes)


def live_children(nodes: Sequence[Node], parent_id: str) -> int:
    return sum(1 for n in nodes if n.parent_id == parent_id and n.status not in ("parked",
                                                                                "failed"))


@dataclass
class Plan:
    action: str  # what will happen (after any fallback)
    parent: Node | None = None  # expand from here; None means no expansion
    mode: str = ""
    count: int = 0
    brief: str = ""
    notes: list[str] = field(default_factory=list)  # why the agent's choice was changed


def room_under(run: Run, nodes: Sequence[Node], parent: Node) -> int:
    """How many children `parent` may still get (0 if blocked), with the reason why not."""
    if parent.depth + 1 > run.caps.max_depth:
        return 0
    return min(run.caps.branching - live_children(nodes, parent.id),
               experiments_left(run, nodes))


def _why_blocked(run: Run, nodes: Sequence[Node], parent: Node) -> str:
    if parent.depth + 1 > run.caps.max_depth:
        return f"{parent.id} is at the depth limit ({run.caps.max_depth})"
    if experiments_left(run, nodes) <= 0:
        return "the experiment budget is used up (queued nodes included)"
    return f"{parent.id} already has {run.caps.branching} live children"


def plan_action(run: Run, nodes: Sequence[Node], node: Node, action: str,
                targets: Sequence[str] = (), brief: str = "") -> Plan:
    by_id = {n.id: n for n in nodes}
    notes: list[str] = []
    if action == "stop":
        return Plan("stop")
    if action == "combine":
        others = [by_id[t] for t in targets if t in by_id and t != node.id
                  and by_id[t].verdict == "supported"]
        if node.verdict != "supported" or not others:
            notes.append("combine needs this node and another node to be supported")
            action = "new_hypothesis"
        else:
            brief = (brief + " Combine with: " + "; ".join(
                f"{o.id} ({o.family}): {o.summary}" for o in others)).strip()
    if action == "transfer":
        target = by_id.get(targets[0]) if targets else None
        if node.verdict != "supported":
            notes.append("transfer needs a supported change")
            action = "new_hypothesis"
        else:
            brief = (brief + f" The change to transfer ({node.id}): {node.summary}").strip()
            parent = target or node
            if room_under(run, nodes, parent) > 0:
                return Plan("transfer", parent, "transfer", 1, brief, notes)
            notes.append(f"transfer blocked: {_why_blocked(run, nodes, parent)}")
            action = "new_hypothesis"
    if action in NODE_ACTIONS:
        count = 2 if action == "more_experiments" else 1
        if room_under(run, nodes, node) > 0:
            return Plan(action, node, action, min(count, room_under(run, nodes, node)), brief,
                        notes)
        notes.append(f"{action} blocked: {_why_blocked(run, nodes, node)}")
        action = "new_hypothesis"
    if action == "new_hypothesis":
        parent = by_id.get(node.parent_id) if node.parent_id else node
        if parent is not None and room_under(run, nodes, parent) > 0:
            return Plan("new_hypothesis", parent, "new_hypothesis",
                        min(2, room_under(run, nodes, parent)), brief, notes)
        if parent is not None:
            notes.append(f"new_hypothesis blocked: {_why_blocked(run, nodes, parent)}")
    return Plan("stop", notes=notes)
