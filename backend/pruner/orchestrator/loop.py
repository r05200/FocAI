"""The orchestrator: owns the tree and moves nodes through hypothesis -> experiment -> synthesis.

RunManager hands every run to Orchestrator.run(). A run with `paths` changes the user's files
and runs their command; a run without files is a research run: hypotheses are guesses at what
the user wants to see, and an experiment searches the vault (and the web, if set up) for resources
whose relevance synthesis then judges (orchestrator/research.py). The run:
  1. backs up the user's files, writes the objectives, settles the experiment command (or asks);
  2. runs the baseline: node n1 is the original files, measured once (if the command fails on
     them the run stops: nothing can be compared). A research run's n1 is the question itself;
  3. expands n1: 2-3 validated, pre-scored hypotheses (orchestrator/proposer.py);
  4. repeats, one step at a time (each step can be paused, stopped, or aborted by an instruction):
       first any expansion a person asked for (a confirmed suggestion or a restore: state.jobs),
       else pick the best waiting node, keeping other families alive (orchestrator/queue.py),
       run its experiment in place (orchestrator/experiment.py),
       judge it and log the finding (orchestrator/synthesis.py),
       turn the agent's next action into an expansion within the budget
       (orchestrator/actions.py);
     until the experiment budget is used or nothing is left to try (covering every objective
     does not end it early: the conclusion waits for all the other branches);
  5. finishes: the best supported version is left applied to the user's files (the original
     files if nothing was supported), the patch from the originals is saved
     (GET /runs/{id}/patch), and a final report is written. The answer becomes a conclusion
     node, a child of the node the run ended on: the best node if it said stop and the
     objectives are covered, else the node judged last (the root if none was). Its report
     combines the results of every branch (final_report.md gets one block per branch), and its
     `combines` lists the nodes it draws on.

Steering (steer): after an instruction or a chip toggle, the manager's amendment task calls
steer(), which re-rates the tree in one batched call and offers suggestions
(orchestrator/steering.py). A person's keep/park/restore is applied by the manager
(orchestrator/human.py); the loop just sees the new statuses.

Manual mode (Run.manual): before each experiment the loop waits for a person to choose which
waiting hypothesis to pursue. The nodes whose proposals wait get awaiting_choice (the UI rings
them in yellow) and the run gets awaiting="choice". Keeping a waiting hypothesis picks it (it runs
next), parking drops it, and turning manual mode off lets the agent choose again at once.

Recovery: after a server restart the manager reloads a running run paused, from the last level
boundary that was saved (RunManager.recover); resuming calls run() again, which skips every stage
the saved tree already has (objectives, root, baseline, first expansion).

The orchestrator never touches the run's bookkeeping directly: it uses the manager (events,
logs, level boundaries, the pause gate, the abortable step).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel

from pruner.agent.toolloop import AgentSession
from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.events import (
    Activity,
    NodeCreated,
    NodeUpdated,
    ObjectivesUpdated,
    RunUpdated,
    VaultRetrieved,
)
from pruner.core.llm import LLM, LLMError
from pruner.core.models import DeadEnd, ForkRequest, LogEntry, Node
from pruner.orchestrator import steering
from pruner.orchestrator.actions import experiments_run, plan_action, room_under, why_blocked
from pruner.orchestrator.experiment import ExperimentPhase, Runner, brief, describe
from pruner.orchestrator.proposer import HypothesisPhase, next_node_ids
from pruner.orchestrator.queue import candidates, select_next
from pruner.orchestrator.research import ResearchPhase, queries_of
from pruner.orchestrator.steering import Job
from pruner.orchestrator.synthesis import SynthesisPhase, baseline_text
from pruner.pruning.postscorer import PostScorer
from pruner.pruning.prescorer import PreScorer
from pruner.pruning.scale import to_ten
from pruner.workspace.runner import run_command

if TYPE_CHECKING:
    from pruner.runs.manager import LiveRun, RunManager


class FinalReport(BaseModel):
    title: str = ""  # a headline: the conclusion node's label
    answer: str


class BaselineFailed(RuntimeError):
    pass


def branches_text(nodes: list[Node]) -> str:
    """One block per branch node (not the root or the conclusion) for the final report: where it
    stands, its result and why it was kept or parked, so the report can combine them."""
    by_id = {n.id: n for n in nodes}
    lines = []
    for n in nodes:
        if n.parent_id is None or n.type == "conclusion":
            continue
        path, cur = [], n
        while cur is not None:
            path.append(cur.id)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
        state = n.verdict or ("not run" if n.experiment is None else n.status)
        line = f"- {' > '.join(reversed(path))} [{n.family or '-'}] {state}: {n.description}"
        if n.synthesis is not None:
            line += f"\n    Found: {n.synthesis.measured}\n    Finding: {n.synthesis.finding}"
        elif n.result:
            line += f"\n    Result: {n.result}"
        if n.decision is not None:
            line += f"\n    {n.decision.verdict.capitalize()} ({n.decision.stage}): " \
                    f"{n.decision.reason}"
        lines.append(line)
    return "\n".join(lines) or "(no branches)"


def best_node(nodes: list[Node]) -> Node | None:
    """The supported, measured node with the best judge score (then confidence), if any."""
    good = [n for n in nodes if n.verdict == "supported" and n.status == "done"
            and n.experiment is not None and not n.experiment.error]
    return max(good, key=lambda n: (n.post_score or 0.0,
                                    n.synthesis.confidence if n.synthesis else 0.0),
               default=None)


class Orchestrator:
    def __init__(self, agent_llm: LLM, prescorer: PreScorer, postscorer: PostScorer,
                 cfg: Config | None = None, runner: Runner = run_command) -> None:
        self.cfg = cfg or get_config()
        self.llm = agent_llm
        self.prescorer, self.postscorer = prescorer, postscorer
        self.hypothesis = HypothesisPhase(agent_llm, prescorer, self.cfg)
        self.experiment = ExperimentPhase(self.cfg, runner)
        self.synthesis = SynthesisPhase(agent_llm, postscorer, self.cfg)
        self.research = ResearchPhase(prescorer.vault, prescorer.llm, self.cfg)

    def llms(self) -> list[LLM]:
        """Every LLM it calls, so the manager can scope them to the run (for stop)."""
        return [self.llm, self.prescorer.llm, self.postscorer.llm]

    # ---- the run

    async def run(self, host: RunManager, state: LiveRun) -> None:
        run, emitter = state.run, state.emitter
        await host._checkpoint(state)
        if not run.objectives:  # a fresh run (a recovered one already has them)
            attachments = await host._setup_files(state)
            spec = next((i.text for i in run.instructions if i.kind == "spec"), "")
            run.objectives, candidate = await host.objectives.create_full(
                question=run.question, spec=spec, directives=run.directives,
                attachments=attachments)
            emitter.emit(ObjectivesUpdated, objectives=run.objectives)
            await host._settle_command(state, candidate, attachments)
        else:
            await host._need_command(state)

        # Each stage below is skipped when the saved tree already has it, so a run reloaded after
        # a server restart carries on from the last level boundary that was written.
        root = next((n for n in state.nodes if n.parent_id is None), None)
        if root is None:
            if state.workspace is None:
                root = Node(id="n1", run_id=run.id, type="reading", status="done",
                            phase="complete", description=run.question,
                            summary="the question (a research run: no files)",
                            decided_by="agent")
                state.nodes.append(root)
                emitter.emit(NodeCreated, node=root)
                emitter.emit(Activity, node_id=root.id, message=(
                    "No files were given, so this is a research run: hypotheses guess what you "
                    "want to see, and experiments search "
                    + ("the vault and the web" if self.research.web_ready()
                       else "the vault (web search is not set up)") + " for resources."))
            else:
                root = Node(id="n1", run_id=run.id, type="experiment", status="pending",
                            phase="experiment", description="Baseline: the files as given, "
                                                            "before any change.",
                            summary="baseline (the original files)",
                            version=state.workspace.info.baseline_version)
                state.nodes.append(root)
                emitter.emit(NodeCreated, node=root)
            host._boundary(state)
        if state.workspace is not None and root.experiment is None:
            root.status = "pending"
            await host._step(state, lambda: self._baseline(host, state, root))
            host._boundary(state)
        if not any(n.parent_id == root.id for n in state.nodes):
            await host._step(state, lambda: self.hypothesis.expand(host, state, root,
                                                                   mode="initial"))
            host._boundary(state)
        judged = [n for n in state.nodes if n.synthesis is not None]
        if state.concluded_from is None and judged:
            state.concluded_from = judged[-1].id

        covered_noted = False
        while True:
            await host._checkpoint(state)
            await state.amends_idle.wait()
            if state.jobs:  # what a person asked for goes first; dropped only once it is done
                job = state.jobs[0]
                await host._step(state, lambda j=job: self._run_job(host, state, j))
                if job in state.jobs:
                    state.jobs.remove(job)
                host._boundary(state)
                continue
            if experiments_run(state.nodes) >= run.caps.node_budget:
                emitter.emit(Activity, message=f"The experiment budget ({run.caps.node_budget})"
                                               f" is used up.")
                break
            if run.manual and self._needs_choice(state):
                self._await_choice(host, state)
                state.choice_changed.clear()
                await state.choice_changed.wait()  # a keep, a park, a suggestion, manual off...
                continue  # check pause, amendments, jobs and the budget again, then the choice
            self._clear_choice(host, state)
            node = select_next(state.nodes, state.focus)
            state.focus = None
            if node is None:
                emitter.emit(Activity, message="Nothing is left to try within the limits.")
                break
            await host._step(state, lambda n=node: self._advance(host, state, n))
            host._boundary(state)
            if not covered_noted and self._covered(state):
                covered_noted = True  # the run does not stop here: the other branches finish first
                emitter.emit(Activity, message="Every objective is covered and the best result's "
                                               "advice was to stop; the branches still waiting "
                                               "finish before the conclusion.")
        await self._finish(host, state)

    # ---- steps

    async def _baseline(self, host: RunManager, state: LiveRun, root: Node) -> None:
        run = state.run
        assert state.workspace is not None and run.command is not None
        root.status = "running"
        host._emit(state, NodeUpdated, node=root, change="running")
        exp = await self.experiment.run(state.workspace, run.command, root.version or "")
        run.totals.experiments_run = experiments_run(state.nodes)
        root.experiment, root.result = exp, brief(exp)
        root.phase = "complete"
        host._log(state, root.id, LogEntry(kind="error" if exp.error else "decision",
                                           title="Baseline measured" if not exp.error
                                           else "The baseline run failed",
                                           text=describe(exp), phase="experiment"))
        if exp.error:
            root.status = "failed"
            host._emit(state, NodeUpdated, node=root, change="failed")
            raise BaselineFailed(f"The experiment command failed on the original files "
                                 f"({exp.error}). Fix the command or the files and start again.")
        root.status = "done"
        root.summary = f"baseline: {brief(exp)}"
        host._emit(state, NodeUpdated, node=root, change="done")

    async def _advance(self, host: RunManager, state: LiveRun, node: Node) -> None:
        """Run one waiting node through experiment and synthesis, then act on its advice."""
        run = state.run
        if node.status != "pending":  # a person parked it between its selection and now
            return
        node.status, node.phase = "running", "experiment"
        host._emit(state, NodeUpdated, node=node, change="running")
        if state.workspace is None:
            host._log(state, node.id, LogEntry(
                kind="activity", title="Searching for resources",
                text="; ".join(queries_of(node, self.cfg)), phase="experiment"))
            exp = await self.research.run(run, node, on_retrieved=lambda people, q, ids, sims:
                                          host._emit(state, VaultRetrieved, node_id=node.id,
                                                     person="+".join(people), query=q,
                                                     item_ids=ids, similarities=sims))
        else:
            assert run.command is not None
            host._log(state, node.id, LogEntry(kind="activity", title="Running the experiment",
                                               text=run.command.text, phase="experiment"))
            exp = await self.experiment.run(state.workspace, run.command, node.version or "")
        run.totals.experiments_run = experiments_run(state.nodes)
        node.experiment, node.result = exp, brief(exp)  # the full text goes to the log
        host._log(state, node.id, LogEntry(kind="error" if exp.error else "decision",
                                           title="Experiment failed" if exp.error
                                           else "Experiment measured"
                                           + (" (reused an identical earlier run)"
                                              if exp.cached else ""),
                                           text=describe(exp), phase="experiment"))
        if exp.error:
            state.dead_ends.append(DeadEnd(run_id=run.id, node_id=node.id,
                                           description=node.full_text(), reason=exp.error))

        await host._checkpoint(state)
        node.phase = "synthesis"
        synthesis = await self.synthesis.run(host, state, node)
        state.concluded_from = node.id
        host._emit(state, NodeUpdated, node=node,
                   change={"failed": "failed", "parked": "parked"}.get(node.status, "done"))

        plan = plan_action(run, state.nodes, node, synthesis.next_action,
                           synthesis.action_targets, synthesis.action_brief)
        note = f" ({'; '.join(plan.notes)})" if plan.notes else ""
        host._log(state, node.id, LogEntry(
            kind="decision", title=f"Next: {plan.action}",
            text=f"The agent chose {synthesis.next_action}: {synthesis.next_reason}{note}",
            phase="synthesis"))
        if plan.action == "stop" or plan.parent is None:
            node.closed = True
            return
        await host._checkpoint(state)
        await self.hypothesis.expand(host, state, plan.parent, mode=plan.mode, brief=plan.brief,
                                     count=plan.count)

    # ---- manual mode

    @staticmethod
    def _needs_choice(state: LiveRun) -> bool:
        """Something could run next, and a person has not picked it yet."""
        pool = {n.id for n in candidates(state.nodes)}
        return bool(pool) and state.focus not in pool

    def _await_choice(self, host: RunManager, state: LiveRun) -> None:
        """Ring the nodes whose proposals wait for a person, and say the run waits."""
        run = state.run
        waiting = {n.parent_id for n in candidates(state.nodes)}
        self._flag_choice(host, state, waiting)
        if run.awaiting != "choice":
            run.awaiting = "choice"
            host._emit(state, RunUpdated, run=run)
            host._emit(state, Activity, message=(
                "Manual mode: the next hypotheses are ready. Keep the one to pursue (it runs "
                "next) and park the ones to drop; turning manual mode off lets the agent choose."))
        host._save(state)

    def _clear_choice(self, host: RunManager, state: LiveRun) -> None:
        self._flag_choice(host, state, set())
        if state.run.awaiting == "choice":
            state.run.awaiting = None
            host._emit(state, RunUpdated, run=state.run)

    @staticmethod
    def _flag_choice(host: RunManager, state: LiveRun, waiting: set) -> None:
        for node in state.nodes:
            flag = node.id in waiting
            if node.awaiting_choice != flag:
                node.awaiting_choice = flag
                host._mirror(state, node)
                host._emit(state, NodeUpdated, node=node, change="awaiting")

    async def _run_job(self, host: RunManager, state: LiveRun, job: Job) -> None:
        node = next((n for n in state.nodes if n.id == job.node_id), None)
        if node is None:
            return
        room = room_under(state.run, state.nodes, node)
        if room <= 0:
            host._log(state, node.id, LogEntry(
                kind="decision", title=f"Could not {job.mode.replace('_', ' ')} here",
                text=f"Asked for by a person, but {why_blocked(state.run, state.nodes, node)}."))
            return
        await self.hypothesis.expand(host, state, node, mode=job.mode, brief=job.brief,
                                     count=min(job.count, room))

    # ---- steering

    async def steer(self, host: RunManager, state: LiveRun, *, change: str,
                    instruction_id: str | None, forks: Sequence[ForkRequest] = ()) -> None:
        """One batched re-rate of the tree after an instruction or a chip toggle, then new
        suggestions (orchestrator/steering.py). Called by the manager's amendment task."""
        run = state.run
        targets = steering.rerate_targets(state.nodes)
        if not targets:
            return
        await host._checkpoint(state)
        root = next((n for n in state.nodes if n.parent_id is None), None)
        measured = (", ".join(sorted(root.experiment.metrics))
                    if root and root.experiment and root.experiment.metrics else "(none)")
        scored = await self.prescorer.rate_for_directive(
            targets, question=run.question, objectives=run.objectives, change=change,
            instructions=run.instructions, directives=run.directives,
            findings="\n".join(f"- {f.node_id or '-'} [{f.verdict}] {f.text}"
                               for f in state.findings[-15:]) or "(none)",
            measured=measured)
        by_id = {n.id: n for n in state.nodes}
        counts = {"parked": 0, "restored": 0}
        for s in scored:
            node = by_id.get(s.node_id)
            if node is None:  # removed by a rewind meanwhile
                continue
            what = steering.apply_rerate(node, s, self.cfg)
            if what == "parked":
                state.dead_ends.append(DeadEnd(run_id=run.id, node_id=node.id,
                                               description=node.full_text(),
                                               reason=node.decision.reason
                                               if node.decision else "parked"))
            elif what == "restored":
                state.dead_ends[:] = [d for d in state.dead_ends if d.node_id != node.id]
            counts[what] = counts.get(what, 0) + 1
            host._mirror(state, node)
            host._log(state, node.id, LogEntry(
                kind="decision",
                title=f"Re-rated for the new direction: {to_ten(s.relevant):.1f} / 10",
                text=s.reason + (f"\nNeeds re-measuring: {', '.join(node.missing_metrics)} was "
                                 f"not measured." if node.needs_remeasure else "")))
            host._emit(state, NodeUpdated, node=node, change=what)
        select_next(state.nodes)  # refresh the queue priorities the suggestions use
        remeasure = sum(n.needs_remeasure for n in state.nodes)
        host._emit(state, Activity, message=(
            f"Re-rated {len(scored)} node(s) for the new direction: {counts['parked']} parked, "
            f"{counts['restored']} back in the queue, {remeasure} need re-measuring."))
        host._offer(state, steering.suggest(run, state.nodes, self.cfg,
                                            instruction_id=instruction_id, forks=forks))

    def _covered(self, state: LiveRun) -> bool:
        """Every objective advanced by some finished node, and the best node said stop."""
        wanted = {o.id for o in state.run.objectives}
        done = {o for n in state.nodes if n.status == "done" for o in n.criteria_progress}
        best = best_node(state.nodes)
        return bool(wanted) and wanted <= done and best is not None and best.synthesis is not \
            None and best.synthesis.next_action == "stop"

    # ---- the end

    def restore_files(self, state: LiveRun) -> Node | None:
        """Write the best supported version (the originals if none) to the user's files, so no
        half-tried change stays. Used when a run ends and when a crashed run is recovered."""
        ws = state.workspace
        if ws is None:
            return None
        best = best_node(state.nodes)
        ws.apply_version(best.version if best and best.version else ws.info.baseline_version)
        return best

    def settle_files(self, host: RunManager, state: LiveRun) -> Node | None:
        """Leave the best supported version applied (the originals if none) and save the patch.
        Also used when a run is stopped or fails, so no half-tried change stays in the files."""
        best = self.restore_files(state)
        ws = state.workspace
        if ws is None:
            return None
        state.run.best_node_id = best.id if best else None
        host.store.save_patch(state.run.id, ws.patch())
        state.run.patch_ready = True
        return best

    async def _finish(self, host: RunManager, state: LiveRun) -> None:
        run = state.run
        self._clear_choice(host, state)
        # By now every branch that could run has run (the loop only ends on the budget or an empty
        # queue). The answer branches off the best node when the objectives are covered and it
        # said stop, else off the node judged last.
        if self._covered(state) and (best_now := best_node(state.nodes)) is not None:
            state.concluded_from = best_now.id
        if state.workspace is None:
            best = best_node(state.nodes)
            run.best_node_id = best.id if best else None
            kept = (f"best direction {best.id} ({best.family}): {best.summary}" if best
                    else "none: no direction was supported")
        else:
            best = await asyncio.to_thread(self.settle_files, host, state)
            kept = (f"{best.id} ({best.family}): {best.summary}" if best
                    else "none: the original files were restored")
            host._emit(state, Activity, node_id=best.id if best else None,
                       message=f"Left applied to the files: {kept}. The patch from the originals "
                               f"is at GET /runs/{run.id}/patch.")
        prompt = prompts.render(
            "final_report", question=run.question,
            instructions=prompts.render_instructions(run.instructions, run.directives),
            objectives=prompts.render_objectives(run.objectives),
            baseline=("(none: a research run without files)" if state.workspace is None
                      else baseline_text(state.nodes)),
            findings="\n".join(f"- {f.node_id or '-'} [{f.verdict}] {f.text}"
                               for f in state.findings) or "(none)",
            branches=branches_text(state.nodes), kept=kept)
        title = ""
        try:
            out = await AgentSession(self.llm, self.cfg).run(
                FinalReport, prompt, model=self.cfg.agent_synthesis_model, purpose="final_report")
            run.final_answer, title = out.value.answer, out.value.title
        except LLMError:  # the run's work is done; a missing report should not fail it
            run.final_answer = (f"Kept: {kept}.\nBranches:\n{branches_text(state.nodes)}\n"
                                f"Findings:\n" + "\n".join(
                                    f"- [{f.verdict}] {f.text}" for f in state.findings))
        self._conclude(host, state, title)

    def _conclude(self, host: RunManager, state: LiveRun, title: str = "") -> Node:
        """The answer as a conclusion node, a child of the node the run ended on."""
        existing = next((n for n in state.nodes if n.type == "conclusion"), None)
        if existing is not None:  # a run recovered after its answer was already written
            existing.result = state.run.final_answer
            return existing
        by_id = {n.id: n for n in state.nodes}
        parent = (by_id.get(state.concluded_from or "")
                  or next(n for n in state.nodes if n.parent_id is None))
        answer = state.run.final_answer or ""
        title = " ".join(title.split())[:120]
        node = Node(id=next_node_ids(state.nodes, 1)[0], run_id=state.run.id,
                    parent_id=parent.id, depth=parent.depth + 1, type="conclusion",
                    status="done", phase="complete", decided_by="agent",
                    description=f"Conclusion: {title}" if title else "Conclusion",
                    combines=[n.id for n in state.nodes if n.synthesis is not None],  # every branch
                    summary=(answer.strip().splitlines() or [""])[0][:200], result=answer,
                    criteria_progress=sorted({o for n in state.nodes if n.status == "done"
                                              for o in n.criteria_progress}))
        state.nodes.append(node)
        host._emit(state, NodeCreated, node=node)
        host._log(state, node.id, LogEntry(kind="decision", title="Answer reached",
                                           text=f"Concluded from {parent.id}.\n{answer}"))
        return node
