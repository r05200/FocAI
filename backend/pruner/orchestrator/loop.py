"""The orchestrator: owns the tree and moves nodes through hypothesis -> experiment -> synthesis.

RunManager hands a run with `paths` to Orchestrator.run() (runs without files keep the single
agent turn). Built so far (M2):
  1. back up the user's files, write the objectives, settle the experiment command (or ask);
  2. the baseline node n1: the original files, the root of the tree;
  3. the first expansion from it (orchestrator/proposer.py): 2-3 validated, pre-scored
     hypotheses, each with its own code version; low ones are parked.
The run then ends with a summary. Running experiments, synthesis and the next-action loop are M3.

The orchestrator never touches the run's bookkeeping directly: it uses the manager (events,
logs, level boundaries, the pause gate, the abortable step) so pause, stop and instructions work
the same as for the single agent turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pruner.core.config import Config, get_config
from pruner.core.events import NodeCreated, ObjectivesUpdated
from pruner.core.llm import LLM
from pruner.core.models import Node
from pruner.orchestrator.proposer import HypothesisPhase
from pruner.pruning.prescorer import PreScorer

if TYPE_CHECKING:
    from pruner.runs.manager import LiveRun, RunManager


class Orchestrator:
    def __init__(self, agent_llm: LLM, prescorer: PreScorer, cfg: Config | None = None) -> None:
        self.cfg = cfg or get_config()
        self.llm = agent_llm
        self.prescorer = prescorer
        self.hypothesis = HypothesisPhase(agent_llm, prescorer, self.cfg)

    def llms(self) -> list[LLM]:
        """Every LLM it calls, so the manager can scope them to the run (for stop)."""
        return [self.llm, self.prescorer.llm]

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
        host._boundary(state)  # level 0 created

        children = await host._step(
            state, lambda: self.hypothesis.expand(host, state, root, mode="initial"))
        host._boundary(state)  # level 1 created
        live = [n for n in children if n.status != "parked"]
        run.final_answer = (
            f"Proposed {len(children)} hypothesis(es) from the original files: {len(live)} to "
            f"run, {len(children) - len(live)} parked. Running experiments is not built yet.")
