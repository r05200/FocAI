"""The orchestrator: owns the tree and moves nodes through hypothesis -> experiment -> synthesis.

RunManager hands a run with `paths` to Orchestrator.run() (runs without files keep the single
agent turn). The run:
  1. backs up the user's files, writes the objectives, settles the experiment command (or asks);
  2. runs the baseline: node n1 is the original files, measured once (if the command fails on
     them the run stops: nothing can be compared);
  3. expands n1: 2-3 validated, pre-scored hypotheses (orchestrator/proposer.py);
  4. repeats, one step at a time (each step can be paused, stopped, or aborted by an instruction):
       pick the best waiting node, keeping other families alive (orchestrator/queue.py),
       run its experiment in place (orchestrator/experiment.py),
       judge it and log the finding (orchestrator/synthesis.py),
       turn the agent's next action into an expansion within the budget
       (orchestrator/actions.py);
     until the experiment budget is used, nothing is left to try, or every objective is covered
     and the best node's own advice was to stop;
  5. finishes: the best supported version is left applied to the user's files (the original
     files if nothing was supported), the patch from the originals is saved
     (GET /runs/{id}/patch), and a final report is written.

The orchestrator never touches the run's bookkeeping directly: it uses the manager (events,
logs, level boundaries, the pause gate, the abortable step).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pydantic import BaseModel

from pruner.agent.toolloop import AgentSession
from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.events import Activity, NodeCreated, NodeUpdated, ObjectivesUpdated
from pruner.core.llm import LLM, LLMError
from pruner.core.models import DeadEnd, LogEntry, Node
from pruner.orchestrator.actions import experiments_run, plan_action
from pruner.orchestrator.experiment import ExperimentPhase, Runner, describe
from pruner.orchestrator.proposer import HypothesisPhase
from pruner.orchestrator.queue import select_next
from pruner.orchestrator.synthesis import SynthesisPhase, baseline_text
from pruner.pruning.postscorer import PostScorer
from pruner.pruning.prescorer import PreScorer
from pruner.workspace.runner import run_command

if TYPE_CHECKING:
    from pruner.runs.manager import LiveRun, RunManager


class FinalReport(BaseModel):
    answer: str


class BaselineFailed(RuntimeError):
    pass


def best_node(nodes: list[Node]) -> Node | None:
    """The supported, measured node with the best judge score (then confidence), if any."""
    good = [n for n in nodes if n.verdict == "supported" and n.experiment is not None
            and not n.experiment.error and n.version]
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

    def llms(self) -> list[LLM]:
        """Every LLM it calls, so the manager can scope them to the run (for stop)."""
        return [self.llm, self.prescorer.llm, self.postscorer.llm]

    # ---- the run

    async def run(self, host: RunManager, state: LiveRun) -> None:
        run, emitter = state.run, state.emitter
        await host._checkpoint(state)
        attachments = await host._setup_files(state)
        spec = next((i.text for i in run.instructions if i.kind == "spec"), "")
        run.objectives, candidate = await host.objectives.create_full(
            question=run.question, spec=spec, directives=run.directives, attachments=attachments)
        emitter.emit(ObjectivesUpdated, objectives=run.objectives)
        await host._settle_command(state, candidate, attachments)

        assert state.workspace is not None
        root = Node(id="n1", run_id=run.id, type="experiment", status="pending",
                    phase="experiment", description="Baseline: the files as given, before any "
                                                    "change.",
                    summary="baseline (the original files)",
                    version=state.workspace.info.baseline_version)
        state.nodes.append(root)
        emitter.emit(NodeCreated, node=root)
        host._boundary(state)

        await host._step(state, lambda: self._baseline(host, state, root))
        host._boundary(state)
        await host._step(state, lambda: self.hypothesis.expand(host, state, root,
                                                               mode="initial"))
        host._boundary(state)

        while True:
            await host._checkpoint(state)
            await state.amends_idle.wait()
            if experiments_run(state.nodes) >= run.caps.node_budget:
                emitter.emit(Activity, message=f"The experiment budget ({run.caps.node_budget})"
                                               f" is used up.")
                break
            node = select_next(state.nodes, state.focus)
            state.focus = None
            if node is None:
                emitter.emit(Activity, message="Nothing is left to try within the limits.")
                break
            await host._step(state, lambda n=node: self._advance(host, state, n))
            host._boundary(state)
            if self._covered(state):
                emitter.emit(Activity, message="Every objective is covered and the best "
                                               "result's advice was to stop.")
                break
        await self._finish(host, state)

    # ---- steps

    async def _baseline(self, host: RunManager, state: LiveRun, root: Node) -> None:
        run = state.run
        assert state.workspace is not None and run.command is not None
        root.status = "running"
        host._emit(state, NodeUpdated, node=root, change="running")
        exp = await self.experiment.run(state.workspace, run.command, root.version or "")
        run.totals.experiments_run = experiments_run(state.nodes)
        root.experiment, root.result = exp, describe(exp)
        root.phase = "complete"
        host._log(state, root.id, LogEntry(kind="error" if exp.error else "decision",
                                           title="Baseline measured" if not exp.error
                                           else "The baseline run failed",
                                           text=root.result, phase="experiment"))
        if exp.error:
            root.status = "failed"
            host._emit(state, NodeUpdated, node=root, change="failed")
            raise BaselineFailed(f"The experiment command failed on the original files "
                                 f"({exp.error}). Fix the command or the files and start again.")
        root.status = "done"
        root.summary = f"baseline: {describe(exp)}"
        host._emit(state, NodeUpdated, node=root, change="done")

    async def _advance(self, host: RunManager, state: LiveRun, node: Node) -> None:
        """Run one waiting node through experiment and synthesis, then act on its advice."""
        run = state.run
        assert state.workspace is not None and run.command is not None
        node.status, node.phase = "running", "experiment"
        host._emit(state, NodeUpdated, node=node, change="running")
        host._log(state, node.id, LogEntry(kind="activity", title="Running the experiment",
                                           text=run.command.text, phase="experiment"))
        exp = await self.experiment.run(state.workspace, run.command, node.version or "")
        run.totals.experiments_run = experiments_run(state.nodes)
        node.experiment, node.result = exp, describe(exp)
        host._log(state, node.id, LogEntry(kind="error" if exp.error else "decision",
                                           title="Experiment failed" if exp.error
                                           else "Experiment measured",
                                           text=node.result, phase="experiment"))
        if exp.error:
            state.dead_ends.append(DeadEnd(run_id=run.id, node_id=node.id,
                                           description=node.description, reason=exp.error))

        await host._checkpoint(state)
        node.phase = "synthesis"
        synthesis = await self.synthesis.run(host, state, node)
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

    def _covered(self, state: LiveRun) -> bool:
        """Every objective advanced by some finished node, and the best node said stop."""
        wanted = {o.id for o in state.run.objectives}
        done = {o for n in state.nodes if n.status == "done" for o in n.criteria_progress}
        best = best_node(state.nodes)
        return bool(wanted) and wanted <= done and best is not None and best.synthesis is not \
            None and best.synthesis.next_action == "stop"

    # ---- the end

    def settle_files(self, host: RunManager, state: LiveRun) -> Node | None:
        """Leave the best supported version applied (the originals if none) and save the patch.
        Also used when a run is stopped or fails, so no half-tried change stays in the files."""
        ws = state.workspace
        if ws is None:
            return None
        best = best_node(state.nodes)
        ws.apply_version(best.version if best and best.version else ws.info.baseline_version)
        state.run.best_node_id = best.id if best else None
        host.store.save_patch(state.run.id, ws.patch())
        state.run.patch_ready = True
        return best

    async def _finish(self, host: RunManager, state: LiveRun) -> None:
        run = state.run
        best = await asyncio.to_thread(self.settle_files, host, state)
        kept = (f"{best.id} ({best.family}): {best.summary}" if best
                else "none: the original files were restored")
        host._emit(state, Activity, node_id=best.id if best else None,
                   message=f"Left applied to the files: {kept}. The patch from the originals is "
                           f"at GET /runs/{run.id}/patch.")
        prompt = prompts.render(
            "final_report", question=run.question,
            instructions=prompts.render_instructions(run.instructions, run.directives),
            objectives=prompts.render_objectives(run.objectives),
            baseline=baseline_text(state.nodes),
            findings="\n".join(f"- {f.node_id or '-'} [{f.verdict}] {f.text}"
                               for f in state.findings) or "(none)",
            kept=kept)
        try:
            out = await AgentSession(self.llm, self.cfg).run(
                FinalReport, prompt, model=self.cfg.agent_synthesis_model, purpose="final_report")
            run.final_answer = out.value.answer
        except LLMError:  # the run's work is done; a missing report should not fail it
            run.final_answer = f"Kept: {kept}.\nFindings:\n" + "\n".join(
                f"- [{f.verdict}] {f.text}" for f in state.findings)
