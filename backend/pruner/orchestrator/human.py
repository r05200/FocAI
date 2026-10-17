"""A person's keep / park / restore on a node (POST /runs/{id}/nodes/{node_id}/keep|park|restore).

  keep     the node stays: a parked node comes back (to the queue if it never ran, else done); a
           waiting node gets the human boost in the queue (+0.2); a finished one is protected
           from re-rates, and the judge can no longer park it.
  park     the node is parked by hand (restorable) and recorded as a dead end for later prompts.
           Waiting nodes under it no longer run. The baseline cannot be parked.
  restore  a parked node comes back, with any parked ancestors on its path, so the run can
           continue from it. Their dead ends are removed and nodes_restored counts them. The
           manager also files a "correction" item in the person's vault, and if the node had
           already run, queues new hypotheses from it.
A person's decision is final: re-rates never change the status of a human-decided node. On a
running node the action is stored (Node.pending_action) and applied once its step finishes.
"""

from __future__ import annotations

from collections.abc import Sequence

from pruner.core.events import NodeChange
from pruner.core.models import DeadEnd, Decision, HumanAction, Node, Run
from pruner.orchestrator.context import ancestors


class IllegalAction(ValueError):
    """The action makes no sense for the node in its current state."""


def check(node: Node, action: HumanAction) -> None:
    if node.type == "conclusion":
        raise IllegalAction("a conclusion is the run's answer; act on the node it came from")
    if action == "park" and node.parent_id is None:
        raise IllegalAction("the baseline cannot be parked: every result is compared with it")
    if action == "restore" and node.status != "parked":
        raise IllegalAction(f"{node.id} is {node.status}, not parked")
    if node.status == "failed":
        raise IllegalAction(f"{node.id} failed; there is nothing to {action}")


def apply(run: Run, nodes: Sequence[Node], dead_ends: list[DeadEnd], node: Node,
          action: HumanAction) -> list[tuple[Node, NodeChange]]:
    """Apply the action (the node must not be running) and return every node it changed, with
    the change to announce. IllegalAction if it makes no sense (see check)."""
    check(node, action)
    if action == "park":
        node.status = "parked"
        node.decision = Decision(verdict="park", stage="human", reason="Parked by hand.")
        node.decided_by = "human"
        if not any(d.node_id == node.id for d in dead_ends):
            dead_ends.append(DeadEnd(run_id=run.id, node_id=node.id,
                                     description=node.description, reason="Parked by hand."))
        return [(node, "parked")]
    path = ([node] if action == "keep"
            else [n for n in ancestors(nodes, node) if n.status == "parked"])
    changed: list[tuple[Node, NodeChange]] = []
    for n in path:
        if n.status == "parked":
            n.status = "done" if n.experiment is not None else "pending"
            dead_ends[:] = [d for d in dead_ends if d.node_id != n.id]
            if action == "restore":
                run.totals.nodes_restored += 1
        n.decision = Decision(verdict="keep", stage="human",
                              reason="Kept by hand." if action == "keep" else "Restored by hand.")
        n.decided_by = "human"
        changed.append((n, "kept" if action == "keep" else "restored"))
    return changed
