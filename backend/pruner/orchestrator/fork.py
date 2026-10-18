"""Forks: restart exploration from a node the amended objectives still fit (FORK_PLAN.md).

When an instruction adds objectives, the steering re-rate scores every node for relevance to them
(one batched call, Node.directive_score). From those scores:

  choose_fork_point()  F = walk down from the root through nodes scoring at least
                       cfg.fork_relevant_at (8/10); F is the deepest node reached, or the lowest
                       common ancestor when several branches qualify, or the root when none does.
  park_set()           what a fork at F parks: every live node off the root-to-F path, plus F's
                       descendants. Never the baseline; nodes already parked or failed stay as
                       they are; a person may keep some flagged nodes live.
  describe()           the card: the path with scores, the deeper choices below F (the slider),
                       what gets parked, how many keeps that overrides, and the flagged nodes.

Nothing changes until a person confirms (RunManager.confirm_fork -> confirm()): the tree is
snapshotted, the set is parked (not as dead ends: off-direction, not failed; restorable, results
kept), a Job proposes new hypotheses at F, and the run is left paused. While a fork waits for a
decision the run starts no new experiment or proposal (Run.awaiting = "fork") and a person's
keep/park/restore is refused. dismiss() just unblocks. undo() puts the snapshot back exactly and
deletes what was created after the fork (with confirm_delete when there is any).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

from pruner.core import prompts
from pruner.core.config import Config
from pruner.core.events import (
    Activity,
    ForkUpdated,
    NodeRemoved,
    NodeUpdated,
    RunUpdated,
    SuggestionResolved,
)
from pruner.core.models import Decision, ForkRequest, ForkStep, LogEntry, Node, Run
from pruner.orchestrator.actions import room_under, why_blocked
from pruner.orchestrator.context import ancestors
from pruner.orchestrator.human import IllegalAction
from pruner.orchestrator.steering import Job
from pruner.pruning.scale import to_ten

if TYPE_CHECKING:
    from pruner.runs.manager import LiveRun, RunManager


class ForkClosed(ValueError):
    """The fork was already confirmed, dismissed, replaced or undone."""


class UndoNeedsConfirm(ValueError):
    """Undoing would delete nodes created after the fork; confirm_delete is needed."""

    def __init__(self, count: int) -> None:
        super().__init__(f"Undo fork: this deletes {count} new node(s) and their results. Send "
                         f"confirm_delete to go ahead.")
        self.count = count


# ---- choosing F and what it parks (pure)


def _live(node: Node) -> bool:
    return node.type != "conclusion" and node.status not in ("parked", "failed")


def _children(nodes: Sequence[Node]) -> dict[str, list[Node]]:
    out: dict[str, list[Node]] = {}
    for n in nodes:
        if n.parent_id is not None:
            out.setdefault(n.parent_id, []).append(n)
    return out


def _relevant(node: Node, cfg: Config) -> bool:
    return node.directive_score is not None and to_ten(node.directive_score) >= cfg.fork_relevant_at


def choose_fork_point(nodes: Sequence[Node], cfg: Config) -> tuple[Node, str]:
    """F and why (decision 2)."""
    root = next(n for n in nodes if n.parent_id is None)
    kids = _children(nodes)
    reached, frontier = [], [root]
    while frontier:
        node = frontier.pop()
        good = [c for c in kids.get(node.id, []) if _live(c) and _relevant(c, cfg)]
        if good:
            frontier.extend(good)
        elif node is not root:
            reached.append(node)  # the deepest relevant node of its chain
    at = f"{cfg.fork_relevant_at:g}/10"
    if not reached:
        return root, (f"No node still scores {at} or more against the amended objectives, so "
                      f"the fork restarts from the root (the baseline).")
    paths = [[n.id for n in ancestors(nodes, r)] for r in reached]
    common = 0
    while all(len(p) > common and p[common] == paths[0][common] for p in paths):
        common += 1
    by_id = {n.id: n for n in nodes}
    fork_at = by_id[paths[0][common - 1]]
    if len(reached) == 1:
        score = to_ten(fork_at.directive_score or 0.0)
        return fork_at, (f"{fork_at.id} is the deepest node on a path that still fits the "
                         f"amended objectives ({score:.1f}/10, at least {at}).")
    return fork_at, (f"{len(reached)} branches still fit the amended objectives "
                     f"({', '.join(r.id for r in reached)}, each at least {at}); {fork_at.id} is "
                     f"where they meet.")


def park_set(nodes: Sequence[Node], fork_at: Node,
             keep_live: Collection[str] = ()) -> list[Node]:
    """Every live node off the root-to-F path, plus F's descendants (decision 3)."""
    on_path = {n.id for n in ancestors(nodes, fork_at)}
    out = []
    for n in nodes:
        if n.parent_id is None or not _live(n) or n.id in keep_live or n.id == fork_at.id:
            continue
        under_f = fork_at.id in {a.id for a in ancestors(nodes, n)[:-1]}
        if n.id not in on_path or under_f:
            out.append(n)
    return out


def chain_below(nodes: Sequence[Node], fork_at: Node) -> list[Node]:
    """The deeper choices for F: follow the most relevant live child down from F."""
    kids = _children(nodes)
    out, node = [], fork_at
    while live := [c for c in kids.get(node.id, []) if _live(c)]:
        node = max(live, key=lambda c: c.directive_score or 0.0)
        out.append(node)
    return out


def _step(node: Node) -> ForkStep:
    return ForkStep(node_id=node.id, description=node.description, depth=node.depth,
                    score=node.directive_score)


def describe(fork: ForkRequest, nodes: Sequence[Node], fork_at: Node, cfg: Config) -> ForkRequest:
    """Fill the card's fields for a fork at `fork_at` (the request keeps its id and reason)."""
    parked = park_set(nodes, fork_at)
    fork.node_id = fork_at.id
    fork.path = [_step(n) for n in ancestors(nodes, fork_at)]
    fork.below = [_step(n) for n in chain_below(nodes, fork_at)]
    fork.park_ids = [n.id for n in parked]
    fork.kept_overridden = sum(1 for n in parked if n.decided_by == "human"
                               and n.decision is not None and n.decision.verdict == "keep")
    fork.flagged_ids = [n.id for n in parked if _relevant(n, cfg)]
    fork.web_search = bool(cfg.search_provider.strip())
    return fork


def plan(run: Run, nodes: Sequence[Node], cfg: Config) -> ForkRequest | None:
    """A fork request for the current tree, or None when it would park nothing."""
    fork_at, reason = choose_fork_point(nodes, cfg)
    fork = describe(ForkRequest(run_id=run.id, node_id=fork_at.id, reason=reason,
                                objective_ids=[o.id for o in run.objectives]), nodes, fork_at, cfg)
    return fork if fork.park_ids else None


def park_for_fork(node: Node, fork_at: str, reason: str | None = None) -> None:
    """Parked by a confirmed fork (or a branch a person concluded): not a failure, so no dead
    end; restorable, and its results are kept."""
    node.status = "parked"
    node.decided_by = "human"  # a person confirmed it; re-rates never change it
    node.pending_action = None
    node.decision = Decision(verdict="park", stage="human", reason=reason or fork_reason(fork_at))


def fork_reason(fork_at: str) -> str:
    return (f"Parked by the fork at {fork_at}: off the amended objectives (restorable; its "
            f"results are kept).")


# ---- confirm, dismiss, undo (on a live run, through the manager)


def _find(state: LiveRun, fork_id: str) -> ForkRequest:
    fork = next((f for f in state.forks if f.id == fork_id), None)
    if fork is None:
        raise KeyError(fork_id)
    return fork


def _close_suggestion(host: RunManager, state: LiveRun, fork: ForkRequest, status: str) -> None:
    s = next((x for x in state.suggestions if x.id == fork.suggestion_id), None)
    if s is not None and s.status == "open":
        s.status = status  # type: ignore[assignment]
        host._emit(state, SuggestionResolved, suggestion=s)


def _unblock(host: RunManager, state: LiveRun, fork: ForkRequest) -> None:
    run = state.run
    if run.fork_id == fork.id:
        run.awaiting, run.fork_id = None, None
    state.fork_decided.set()


def preview(state: LiveRun, fork_id: str, at: str | None, cfg: Config) -> ForkRequest:
    """The card for a fork at `at` (another node on the path or below F), without changing it."""
    fork = _find(state, fork_id)
    fork_at = _target(state, fork, at)
    return describe(fork.model_copy(deep=True), state.nodes, fork_at, cfg)


def _target(state: LiveRun, fork: ForkRequest, at: str | None) -> Node:
    by_id = {n.id: n for n in state.nodes}
    planned = by_id.get(fork.node_id)
    if planned is None or (not _live(planned) and planned.parent_id is not None):
        raise IllegalAction(f"{fork.node_id} is no longer a live node; dismiss this fork")
    if at is None or at == planned.id:
        return planned
    # up the path to the root, or down anywhere under F (the card suggests the most relevant
    # chain in `below`)
    allowed = {n.id for n in ancestors(state.nodes, planned)} | {
        n.id for n in state.nodes if _live(n)
        and planned.id in {x.id for x in ancestors(state.nodes, n)[:-1]}}
    if at not in allowed or at not in by_id:
        raise IllegalAction(f"{at} is not on the path through {planned.id} or under it; pick "
                            f"a node from the card's path")
    return by_id[at]


def confirm(host: RunManager, state: LiveRun, fork_id: str, at: str | None,
            keep_live: Collection[str]) -> ForkRequest:
    fork = _find(state, fork_id)
    if fork.status != "requested":
        raise ForkClosed(f"fork {fork_id} is already {fork.status}")
    run, cfg = state.run, host.cfg
    fork_at = _target(state, fork, at)
    host.store.save_fork_snapshot(run.id, fork.id, state.snapshot().model_copy(deep=True))
    describe(fork, state.nodes, fork_at, cfg)
    parked, deferred = [], []
    for node in park_set(state.nodes, fork_at, keep_live):
        if node.status == "running":  # its experiment finishes first, then it is parked
            state.fork_parks[node.id] = fork_reason(fork_at.id)
            deferred.append(node.id)
            continue
        park_for_fork(node, fork_at.id)
        host._mirror(state, node)
        host._emit(state, NodeUpdated, node=node, change="parked")
        parked.append(node.id)
    fork_at.closed = False
    host._mirror(state, fork_at)
    room = room_under(run, state.nodes, fork_at)
    if fork_at.parent_id is not None and fork_at.status == "pending":
        # F is a hypothesis that never ran: it runs first, then grows as usual
        state.focus = fork_at.id
        host._log(state, fork_at.id, LogEntry(
            kind="decision", title="Runs next after the fork",
            text=f"{fork_at.id} has not run yet, so it runs first; new hypotheses grow from it "
                 f"after it is judged."))
    elif room > 0:
        new = [o for o in run.objectives if o.source != "spec"]
        brief = prompts.render(
            "fork_brief", fork_at=f"{fork_at.id} ({fork_at.description})",
            objectives=prompts.render_objectives(run.objectives),
            amended=prompts.render_objectives(new) if new else "(none)",
            parked=str(len(parked) + len(deferred)),
            web=("You may search the web for ideas." if fork.web_search else
                 "Web search is not set up, so rely on the code, the vault and the findings."))
        state.jobs.append(Job(fork_at.id, "new_hypothesis", brief, count=min(2, room),
                              fork_id=fork.id))
    else:  # say so: the fork still parks, but nothing new will grow from F
        why = why_blocked(run, state.nodes, fork_at)
        host._log(state, fork_at.id, LogEntry(
            kind="decision", title="No new hypotheses after the fork",
            text=f"Nothing new can grow from {fork_at.id}: {why}."))
        host._emit(state, Activity, node_id=fork_at.id, message=(
            f"The fork parks as confirmed, but no new hypotheses are queued at {fork_at.id}: "
            f"{why}."))
    fork.status, fork.confirmed_at_node = "confirmed", fork_at.id
    fork.park_ids = parked + deferred
    _close_suggestion(host, state, fork, "confirmed")
    _unblock(host, state, fork)
    run.paused = True  # decision 9: resume runs the new hypotheses
    state.gate.clear()
    run.totals.nodes_parked = sum(n.status == "parked" for n in state.nodes)
    host._log(state, fork_at.id, LogEntry(
        kind="decision", title=f"Forked at {fork_at.id}",
        text=f"{fork.reason}\nParked {len(fork.park_ids)} node(s) off this path. New "
             f"hypotheses come from here on resume."))
    host._emit(state, Activity, node_id=fork_at.id, message=(
        f"Forked at {fork_at.id}: parked {len(fork.park_ids)} node(s) off the amended "
        f"objectives. The run is paused; resume it to explore from {fork_at.id}. Undo restores "
        f"the tree as it was."))
    host._emit(state, RunUpdated, run=run)
    host._emit(state, ForkUpdated, fork=fork)
    host.store.save_forks(run.id, state.forks)
    host._save(state)
    return fork


def dismiss(host: RunManager, state: LiveRun, fork_id: str) -> ForkRequest:
    fork = _find(state, fork_id)
    if fork.status != "requested":
        raise ForkClosed(f"fork {fork_id} is already {fork.status}")
    fork.status = "dismissed"
    _close_suggestion(host, state, fork, "dismissed")
    _unblock(host, state, fork)
    host._emit(state, Activity, message="Fork dismissed: nothing was parked; the run carries on "
                                        "with the amended objectives.")
    host._emit(state, RunUpdated, run=state.run)
    host._emit(state, ForkUpdated, fork=fork)
    host.store.save_forks(state.run.id, state.forks)
    host._save(state)
    return fork


def replace_open(host: RunManager, state: LiveRun) -> list[str]:
    """A new amendment replaces a fork still waiting for a decision (decision 11)."""
    replaced = []
    for fork in state.forks:
        if fork.status == "requested":
            fork.status = "replaced"
            _close_suggestion(host, state, fork, "replaced")
            host._emit(state, ForkUpdated, fork=fork)
            replaced.append(fork.id)
    return replaced


def undo(host: RunManager, state: LiveRun, fork_id: str, confirm_delete: bool) -> ForkRequest:
    """Put back the tree as it was just before the fork (decision 10)."""
    fork = _find(state, fork_id)
    if fork.status != "confirmed":
        raise ForkClosed(f"fork {fork_id} is {fork.status}; only a confirmed fork can be undone")
    run = state.run
    snap = host.store.fork_snapshot(run.id, fork.id)
    if snap is None:
        raise IllegalAction(f"the tree saved before fork {fork_id} is missing")
    before = {n.id for n in snap.nodes}
    new = [n for n in state.nodes if n.id not in before]
    if new and not confirm_delete:
        raise UndoNeedsConfirm(len(new))
    # nothing may keep working on the tree being replaced: hold the run, stop the step in flight
    run.paused = True
    state.gate.clear()
    if state.step is not None and not state.step.done():
        state.aborting = True
        state.abort_note = "The fork was undone: the step in progress was stopped."
        state.step.cancel()
    gone = {n.id for n in new}
    for node in new:
        host.store.delete_node_logs(run.id, node.id)
        host._emit(state, NodeRemoved, node_id=node.id)
    current = {n.id: n.model_dump_json() for n in state.nodes}
    state.nodes[:] = [n.model_copy(deep=True) for n in snap.nodes]
    for node in state.nodes:  # a node mid-experiment when the fork was confirmed starts over
        if node.status == "running":
            node.status, node.phase = "pending", "hypothesis"
            node.experiment = node.synthesis = node.verdict = node.result = None
    state.dead_ends[:] = [d.model_copy(deep=True) for d in snap.dead_ends]
    for node in state.nodes:
        if current.get(node.id) != node.model_dump_json():
            host._emit(state, NodeUpdated, node=node, change="restored")
    if gone:
        state.findings[:] = [f for f in state.findings if f.node_id not in gone]
        host.store.save_findings(run.id, state.findings)
        vault = host.store.run_vault(run.id)
        if vault is not None:
            vault.ideas = [i for i in vault.ideas if not set(i.node_ids) & gone]
            host.store.save_run_vault(vault)
            state.ideas[:] = list(vault.ideas)
        for s in state.suggestions:
            if s.status == "open" and s.node_id in gone:
                s.status = "replaced"
    state.jobs[:] = [j for j in state.jobs if j.fork_id != fork.id and j.node_id not in gone]
    state.fork_parks = {k: v for k, v in state.fork_parks.items() if k not in gone}
    if state.focus in gone:
        state.focus = None
    fork.status = "undone"
    run.totals.nodes_parked = sum(n.status == "parked" for n in state.nodes)
    run.totals.experiments_run = sum(n.experiment is not None for n in state.nodes)
    host._emit(state, Activity, message=(
        f"Fork at {fork.confirmed_at_node or fork.node_id} undone: the tree is back as it was"
        + (f" ({len(new)} node(s) created since were deleted)" if new else "")
        + ". The run is paused."))
    host._emit(state, RunUpdated, run=run)
    host._emit(state, ForkUpdated, fork=fork)
    host.store.save_forks(run.id, state.forks)
    host._boundary(state)  # the restored tree is what a rewind or a reload goes back to
    return fork
