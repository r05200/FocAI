"""Starts runs, keeps them going in the background, and handles prompts sent mid-run.

start() turns a prompt (StartRunRequest) into a Run, saves its first event, and spins up the
agent as an asyncio task. The task:
  1. writes the run's objectives from the spec (supporting LLM),
  2. runs the agent on its own LLM, shown in the tree as a root node,
  3. ends the run: run_completed with the final answer, or run_failed on an error.

instruct() handles a later prompt (InstructionRequest): it records the instruction, then in the
background amends the objectives and, if any objective was added, runs the amend-objectives agent
over the tree (re-rating nodes and requesting forks where every branch is low).

Every step is appended to the run's event log (RunStore). The tree is written to disk only at
level boundaries: when a level is created and when it is completed (_boundary), so a page reload
of a running run shows the start of the current level. A stop (or an error) saves the live tree as
it is. Reloading an unfinished run from disk goes back to the start of its current level: its
nodes recover the state they had when the level was created. A run's live state (run, nodes) is
shared by its tasks, so a mid-run instruction and the agent see the same objects. All LLM calls
happen inside `llm.scope(run_id)`, so the stop route can cancel them; a stopped run is ended by
stop() (it saves the final event), so tasks just exit quietly.

Instructions (instruct) are refused (RunNotRunning / ObjectivesNotReady) once the run has
finished or before its objectives are written. While the run is paused they are queued: the amend
step waits at the gate with everything else. While a step is running they abort it: the step is
cancelled, the level is rewound to its start, the amendment runs, then the step starts again with
the new instructions. Any error that is not a failed amendment ends the run (_fail).

pause()/resume() close and open a per-run gate. While it is closed, the run's next step (writing
objectives, the agent's turn, the amend agent's next layer, or any step an instruction starts)
waits at a checkpoint. Calls already in flight are not cancelled; they finish first. Stop still
works while paused: cancelling the run's tasks releases anything waiting on the gate.

Files and the experiment command: a run started with `paths` first backs up the user's editable
files (workspace/workspace.py; they are edited in place later), then the objectives are written and
the run command is taken from the user's own text (runs/command.py). If no command can be verified,
the run asks for it (a "command" question) and waits until it is answered.

Orchestrator: a run with `paths`, given an orchestrator, is handed to it (orchestrator/loop.py):
it owns the tree and calls back here for events, logs, level boundaries, the pause gate and the
abortable step (_step), so pause, stop and instructions behave the same. Runs without files keep
the single agent turn (_single_turn).

Tools: with a vault store, the agent's step gets its tools (agent/tools.py phase_tools) through a
ToolRunner. Every call is logged on the node with the reason the agent gave (node_log events,
data/runs/<id>/logs/<node>.jsonl); the write tools add to the run's findings log and run vault.

Stopping or failing a run with files leaves the best supported version applied to the user's
files (the originals if none) and saves the patch, so a half-tried change never stays.

Not built yet: pushing events to connected clients (the SSE stream), human node actions and
steering re-rates (M4), and acting on fork requests.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from pruner.agent.agent import Agent
from pruner.agent.amend import AmendObjectivesAgent
from pruner.agent.toolloop import ToolRunner
from pruner.agent.tools import ToolContext, phase_tools
from pruner.core.config import Config, get_config
from pruner.core.events import (
    Activity,
    EventBase,
    FindingAdded,
    IdeaAdded,
    InstructionAdded,
    NodeCreated,
    NodeLog,
    NodeUpdated,
    ObjectivesUpdated,
    QuestionAnswered,
    QuestionAsked,
    RunCompleted,
    RunFailed,
    RunStarted,
    RunUpdated,
)
from pruner.core.llm import LLMCancelled, LLMError
from pruner.core.models import (
    Caps,
    DeadEnd,
    Finding,
    Instruction,
    InstructionRequest,
    LogEntry,
    Node,
    Question,
    Run,
    RunCommand,
    RunIdea,
    RunSnapshot,
    RunVault,
    StartRunRequest,
    TokenUsage,
    ToolCallRecord,
)
from pruner.runs.command import verify_command
from pruner.runs.objectives import ObjectiveMaker
from pruner.runs.store import RunStore
from pruner.vault.store import VaultStore
from pruner.workspace.workspace import Workspace

if TYPE_CHECKING:
    from pruner.orchestrator.loop import Orchestrator

log = logging.getLogger(__name__)

T = TypeVar("T")


class Emitter:
    """Numbers a run's events (from 1) and appends them to the store."""

    def __init__(self, store: RunStore, run_id: str, last_seq: int = 0) -> None:
        self.store, self.run_id, self.seq = store, run_id, last_seq

    def emit(self, cls: type[EventBase], **fields) -> EventBase:
        self.seq += 1
        event = cls(seq=self.seq, run_id=self.run_id, **fields)
        self.store.append_event(event)  # type: ignore[arg-type]
        return event


class RunNotRunning(ValueError):
    """The run already finished, so it cannot be paused or resumed."""

    def __init__(self, status: str) -> None:
        super().__init__(f"run already {status}")
        self.status = status


class QuestionClosed(ValueError):
    """The question was already answered."""


class ObjectivesNotReady(ValueError):
    """The run's objectives are not written yet, so it cannot take an instruction."""

    def __init__(self) -> None:
        super().__init__("the objectives are still being written")


def _open_event() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


@dataclass
class LiveRun:
    """A run's state while something is working on it, shared by all of its tasks."""

    run: Run
    emitter: Emitter
    gate: asyncio.Event = field(default_factory=asyncio.Event)  # set = open, clear = paused
    nodes: list[Node] = field(default_factory=list)
    dead_ends: list[DeadEnd] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    tasks: set[asyncio.Task] = field(default_factory=set)
    answers: dict[str, asyncio.Future] = field(default_factory=dict)  # question id -> waiter
    workspace: Workspace | None = None
    tool_seen: dict[str, str] = field(default_factory=dict)  # tool results reused within the run
    focus: str | None = None  # a node the orchestrator should run next (a confirmed suggestion)
    level: int = 0  # depth of the level in progress
    level_start: RunSnapshot | None = None  # the tree when that level was created
    step: asyncio.Task | None = None  # the agent's step in flight, which an instruction aborts
    aborting: bool = False  # the step was cancelled by an instruction (not by a stop)
    amends_open: int = 0  # instructions whose amendment has not finished
    amends_idle: asyncio.Event = field(default_factory=_open_event)  # set when amends_open is 0
    amend_lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one amendment at a time

    def snapshot(self) -> RunSnapshot:
        """The tree as it is right now."""
        return RunSnapshot(run=self.run, nodes=self.nodes, dead_ends=self.dead_ends,
                           questions=self.questions, findings=self.findings)

    def saved(self) -> RunSnapshot:
        """What is saved between level boundaries: the live run, with the level in progress as
        it was when it was created."""
        if self.level_start is None:
            return self.snapshot()
        origin = {n.id: n for n in self.level_start.nodes}
        nodes = [origin[n.id] if n.depth >= self.level else n
                 for n in self.nodes if n.depth < self.level or n.id in origin]
        return RunSnapshot(run=self.run, nodes=nodes, dead_ends=self.dead_ends,
                           questions=self.questions, findings=self.findings)


class RunManager:
    def __init__(self, store: RunStore, agent: Agent, objectives: ObjectiveMaker,
                 cfg: Config | None = None, *,
                 amender: AmendObjectivesAgent | None = None,
                 vault: VaultStore | None = None,
                 orchestrator: Orchestrator | None = None) -> None:
        self.store, self.agent, self.objectives, self.amender = store, agent, objectives, amender
        self.vault = vault  # gives the agent its tools; without it the agent answers from the prompt
        self.orchestrator = orchestrator  # runs with files go through it (orchestrator/loop.py)
        self.cfg = cfg or get_config()
        self._live: dict[str, LiveRun] = {}

    def _new_run(self, req: StartRunRequest) -> Run:
        people = req.people or [req.primary_person]
        instructions = ([Instruction(kind="spec", text=req.spec.strip())]
                        if req.spec.strip() else [])
        return Run(
            question=req.question, instructions=instructions, directives=list(req.directives),
            people=people, primary_person=req.primary_person,
            vault_people=(req.vault_people if req.vault_people is not None
                          else [req.primary_person]),
            mode=req.mode, paths=list(req.paths),
            caps=Caps(max_depth=self.cfg.max_depth, branching=self.cfg.branching,
                      node_budget=self.cfg.node_budget,
                      tool_calls_per_phase=self.cfg.tool_calls_per_phase),
        )

    def _spawn(self, state: LiveRun, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        state.tasks.add(task)

        def done(t: asyncio.Task) -> None:
            state.tasks.discard(t)
            if not state.tasks:
                self._live.pop(state.run.id, None)

        task.add_done_callback(done)
        return task

    def _running(self, run_id: str) -> LiveRun:
        """The live state of an unfinished run, loaded from disk if nothing is working on it
        (back at the start of its current level). KeyError if there is no such run,
        RunNotRunning if it has finished (nothing is loaded or kept for a finished run)."""
        state = self._live.get(run_id)
        if state is not None:
            if state.run.status != "running":
                raise RunNotRunning(state.run.status)
            return state
        snap = self.store.snapshot(run_id)
        if snap is None:
            raise KeyError(run_id)
        if snap.run.status != "running":
            raise RunNotRunning(snap.run.status)
        start = self.store.level_start(run_id)
        nodes = [n.model_copy(deep=True) for n in (start or snap).nodes]
        state = LiveRun(run=snap.run, emitter=Emitter(self.store, run_id,
                                                      self.store.last_seq(run_id)),
                        nodes=nodes, dead_ends=list(snap.dead_ends),
                        questions=list(snap.questions), findings=list(snap.findings),
                        level_start=start, level=max((n.depth for n in nodes), default=0),
                        workspace=Workspace.load(run_id, self.cfg) if snap.run.paths else None)
        if not snap.run.paused:
            state.gate.set()
        self._live[run_id] = state
        return state

    def _save(self, state: LiveRun) -> None:
        self.store.save_snapshot(state.saved())

    def _boundary(self, state: LiveRun) -> None:
        """A level was created or completed: this tree is what a reload goes back to."""
        snap = state.snapshot().model_copy(deep=True)
        state.level_start = snap
        state.level = max((n.depth for n in state.nodes), default=0)
        self.store.save_snapshot(snap)
        self.store.save_level_start(snap)

    def _rewind_level(self, state: LiveRun) -> None:
        """Put the tree back to how it was at the last level boundary: nodes created since are
        removed, the others get their fields back (an orchestrator step can touch nodes at any
        depth, e.g. run a depth-1 node and give it children)."""
        assert state.level_start is not None
        origin = {n.id: n for n in state.level_start.nodes}
        state.nodes[:] = [n for n in state.nodes if n.id in origin]
        for node in state.nodes:
            for name in Node.model_fields:
                setattr(node, name, copy.deepcopy(getattr(origin[node.id], name)))
        state.emitter.emit(Activity, message="A new instruction arrived: the current step was "
                                             "aborted and will start again.")
        for node in state.nodes:
            if node.depth >= state.level and node.status == "running":
                state.emitter.emit(NodeUpdated, node=node, change="running")

    def _settle_files(self, state: LiveRun) -> None:
        """When a run with files ends early (stop or error), leave the best supported version
        applied (the original files if none), so a half-tried change never stays."""
        if self.orchestrator is None or state.workspace is None:
            return
        try:
            self.orchestrator.settle_files(self, state)
        except (OSError, KeyError):
            log.exception("could not restore the files of run %s", state.run.id)

    def _fail(self, state: LiveRun, error: str) -> None:
        """End the run with an error: the tree is saved as it is and the other tasks stop."""
        self._settle_files(state)
        state.run.status = "failed"
        state.run.paused = False
        state.emitter.emit(RunFailed, error=error)
        self.store.save_snapshot(state.snapshot())
        for task in state.tasks:
            if task is not asyncio.current_task():
                task.cancel()
        state.gate.set()

    def _scopes(self, run_id: str) -> ExitStack:
        """Tag every LLM call made for this run with its id, so the stop route reaches them."""
        llms = [self.objectives.llm, self.agent.llm]
        if self.amender is not None:
            llms.append(self.amender.scorer.llm)
        if self.orchestrator is not None:
            llms += self.orchestrator.llms()
        stack = ExitStack()
        for llm in dict.fromkeys(llms):  # the scorers and objectives usually share one LLM
            stack.enter_context(llm.scope(run_id))
        return stack

    async def start(self, req: StartRunRequest) -> Run:
        """Create the run, record it, and start the agent in the background."""
        run = self._new_run(req)
        state = LiveRun(run=run.model_copy(deep=True), emitter=Emitter(self.store, run.id))
        state.gate.set()
        self._live[run.id] = state
        state.emitter.emit(RunStarted, run=run)
        self.store.save_snapshot(RunSnapshot(run=run, nodes=[]))  # so it shows up as running
        self.store.save_run_vault(RunVault(run_id=run.id))
        self._spawn(state, self._run(state))
        return run

    # ---- questions

    async def answer(self, run_id: str, question_id: str, text: str) -> Question:
        """Record a person's answer. Answering the "command" question sets the run's command
        (exactly as typed) and lets the run continue. KeyError if the run or question is unknown,
        RunNotRunning if the run finished, QuestionClosed if it was already answered."""
        state = self._running(run_id)
        question = next((q for q in state.questions if q.id == question_id), None)
        if question is None:
            raise KeyError(question_id)
        if question.status == "answered":
            raise QuestionClosed(f"question {question_id} was already answered")
        answer = text.strip()
        if not answer:
            raise ValueError("the answer is empty")
        question.status, question.answer = "answered", answer
        state.emitter.emit(QuestionAnswered, question=question)
        if question.purpose == "command":
            state.run.command = RunCommand(text=answer, source="user_answer",
                                           source_name=question.id)
            state.run.awaiting = None
            state.emitter.emit(RunUpdated, run=state.run)
        self._save(state)
        waiter = state.answers.pop(question_id, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(answer)
        return question

    async def _ask(self, state: LiveRun, text: str, purpose: str) -> str:
        """Ask the run's primary person a question and wait for the answer (Stop cancels it)."""
        question = Question(run_id=state.run.id, person=state.run.primary_person, text=text,
                            purpose=purpose)  # type: ignore[arg-type]
        waiter = asyncio.get_running_loop().create_future()
        state.answers[question.id] = waiter
        state.questions.append(question)
        if purpose == "command":
            state.run.awaiting = "command"
        state.emitter.emit(QuestionAsked, question=question)
        state.emitter.emit(RunUpdated, run=state.run)
        self._save(state)
        return await waiter

    # ---- workspace, command, logs and findings

    async def _setup_files(self, state: LiveRun) -> dict[str, str]:
        """Back up the user's files (if the run has paths) and return the texts the command may
        be quoted from."""
        run = state.run
        if not run.paths:
            return {}
        state.workspace = await asyncio.to_thread(Workspace.create, run.id, run.paths, self.cfg)
        run.workspace = state.workspace.info
        state.emitter.emit(RunUpdated, run=run)
        state.emitter.emit(Activity, message=f"Backed up {len(run.workspace.files)} editable "
                                             f"file(s) under {run.workspace.root}; experiments "
                                             f"will edit them in place.")
        return state.workspace.attachments_text()

    async def _settle_command(self, state: LiveRun, candidate, attachments: dict[str, str]) -> None:
        """Keep the command the objectives LLM found only if the user wrote it; else ask."""
        run = state.run
        if state.workspace is None or run.command is not None:
            return
        sources = {"question": run.question,
                   **{("spec" if i.kind == "spec" else f"instruction {i.id}"): i.text
                      for i in run.instructions},
                   **attachments}
        command, why = verify_command(candidate.run_command, sources,
                                      state.workspace.roots.root,
                                      result_hint=candidate.result_hint)
        if command is not None:
            run.command = command
            state.emitter.emit(RunUpdated, run=run)
            state.emitter.emit(Activity, message=f"Experiment command (from the "
                                                 f"{command.source_name}): {command.text}")
            return
        root = state.workspace.roots.root
        await self._ask(state, (f"What command runs one experiment in {root}? ({why}.) Type it "
                                f"exactly as it should run, e.g. `python bench.py`; it should "
                                f"print or write a JSON result."), "command")

    @staticmethod
    def _emit(state: LiveRun, cls: type[EventBase], **fields) -> EventBase:
        return state.emitter.emit(cls, **fields)

    def _log(self, state: LiveRun, node_id: str, entry: LogEntry) -> None:
        self.store.append_log(state.run.id, node_id, entry)
        state.emitter.emit(NodeLog, node_id=node_id, entry=entry)

    def _log_call(self, state: LiveRun, node_id: str, record: ToolCallRecord) -> None:
        self._log(state, node_id, LogEntry(kind="tool_call", title=f"Called {record.tool}",
                                           text=record.reason, tool=record.tool,
                                           args=record.args, phase=record.phase))
        self._log(state, node_id, LogEntry(
            kind="tool_result", title=f"{record.tool} returned"
            + (" (reused from an earlier identical call)" if record.cached else ""),
            text=record.result_preview, tool=record.tool, phase=record.phase))

    def _add_finding(self, state: LiveRun, finding: Finding) -> None:
        state.findings.append(finding)
        self.store.append_finding(finding)
        state.emitter.emit(FindingAdded, finding=finding)

    def _add_idea(self, state: LiveRun, idea: RunIdea) -> None:
        vault = self.store.run_vault(state.run.id) or RunVault(run_id=state.run.id)
        vault.ideas.append(idea)
        self.store.save_run_vault(vault)
        state.emitter.emit(IdeaAdded, idea=idea)

    def _runner(self, state: LiveRun, node: Node, phase: str = "hypothesis") -> ToolRunner | None:
        """The node's tools for `phase`, or None when the manager has no vault (no tools)."""
        if self.vault is None:
            return None
        ctx = ToolContext(run=state.run, nodes=state.nodes, vault=self.vault, cfg=self.cfg,
                          workspace=state.workspace, version=node.version, node_id=node.id,
                          on_finding=lambda f: self._add_finding(state, f),
                          on_branch_finding=lambda i: self._add_idea(state, i))
        return ToolRunner(phase_tools(ctx, phase), phase=phase, cfg=self.cfg,  # type: ignore[arg-type]
                          on_call=lambda r: self._log_call(state, node.id, r),
                          seen=state.tool_seen)

    async def instruct(self, run_id: str, req: InstructionRequest) -> Instruction:
        """Record a mid-run prompt now; amend the objectives and re-check the tree in the
        background. While a step is running (and the run is not paused) the step is aborted
        first. KeyError if the run is unknown, RunNotRunning if it finished, ObjectivesNotReady
        if its objectives are not written yet."""
        state = self._running(run_id)
        if not state.run.objectives:
            raise ObjectivesNotReady
        instruction = Instruction(kind="steer", text=req.text.strip())
        state.run.instructions.append(instruction)
        if req.directives is not None:
            state.run.directives = list(req.directives)
        state.emitter.emit(InstructionAdded, instruction=instruction)
        self._save(state)
        state.amends_open += 1
        state.amends_idle.clear()
        if not state.run.paused and state.step is not None and not state.step.done():
            state.aborting = True
            state.step.cancel()
        self._spawn(state, self._amend(state, instruction))
        return instruction

    async def pause(self, run_id: str) -> Run:
        """Hold the run: its next step waits until resume(). Nothing in flight is cancelled.
        KeyError if unknown, RunNotRunning if it already finished. Pausing twice is fine."""
        state = self._running(run_id)
        if not state.run.paused:
            state.gate.clear()
            state.run.paused = True
            state.emitter.emit(Activity, message="Paused: the agent takes no further step "
                                                 "until it is resumed.")
            self._save(state)
        return state.run

    async def resume(self, run_id: str) -> Run:
        """Open the gate so the run carries on from where it was. Same errors as pause()."""
        state = self._running(run_id)
        if state.run.paused:
            state.run.paused = False
            state.gate.set()
            state.emitter.emit(Activity, message="Resumed.")
            self._save(state)
        return state.run

    @staticmethod
    async def _checkpoint(state: LiveRun) -> None:
        """Wait here while the run is paused."""
        await state.gate.wait()

    def is_running(self, run_id: str) -> bool:
        return run_id in self._live and bool(self._live[run_id].tasks)

    async def cancel(self, run_id: str) -> bool:
        """Cancel the run's tasks and wait for them to end. False if none was running here."""
        state = self._live.get(run_id)
        if state is None or not state.tasks:
            return False
        tasks = list(state.tasks)
        for t in tasks:
            t.cancel()
        state.gate.set()  # nothing may stay blocked on a paused run that is being stopped
        await asyncio.gather(*tasks, return_exceptions=True)
        return True

    async def stop(self, run_id: str) -> RunFailed:
        """End a run the user stopped: cancel its tasks, then save the tree as it is with the
        final run_failed event. KeyError if the run is unknown."""
        state = self._live.get(run_id)
        await self.cancel(run_id)
        if state is not None:
            await asyncio.to_thread(self._settle_files, state)
        return self.store.mark_stopped(run_id, state.snapshot() if state else None)

    async def wait(self, run_id: str) -> None:
        """Wait until every task of the run is finished (used by tests and shutdown)."""
        while (state := self._live.get(run_id)) and state.tasks:
            await asyncio.gather(*list(state.tasks), return_exceptions=True)

    async def _amend(self, state: LiveRun, instruction: Instruction) -> None:
        run, emitter = state.run, state.emitter
        try:
            async with state.amend_lock:
                with self._scopes(run.id):
                    await self._checkpoint(state)
                    new = await self.objectives.amend(
                        run.objectives, instruction, question=run.question,
                        directives=run.directives)
                    if not new:
                        emitter.emit(Activity, message="The instruction added no new objectives.")
                    else:
                        run.objectives = [*run.objectives, *new]
                        emitter.emit(ObjectivesUpdated, objectives=run.objectives)
                        if self.amender is not None and state.nodes:
                            result = await self.amender.run(
                                run, state.nodes, lambda: self._checkpoint(state))
                            by_id = {n.id: n for n in state.nodes}
                            for s in result.rated:
                                emitter.emit(NodeUpdated, node=by_id[s.node_id], change="scored")
                            for fork in result.forks:
                                emitter.emit(
                                    Activity, node_id=fork.node_id,
                                    message=f"Backtracking: fork requested here. {fork.reason}")
        except (LLMCancelled, asyncio.CancelledError):
            log.info("amendment for run %s was stopped", run.id)
        except (LLMError, ValueError, OSError) as e:  # a failed amendment does not end the run
            log.exception("amendment for run %s failed", run.id)
            emitter.emit(Activity, message=f"Could not apply the instruction: {e}")
        except Exception as e:
            log.exception("amendment for run %s failed unexpectedly", run.id)
            self._fail(state, str(e))
        finally:
            if run.status == "running":
                self._save(state)
            state.amends_open -= 1
            if state.amends_open == 0:
                state.amends_idle.set()

    async def _step(self, state: LiveRun, make: Callable[[], Awaitable[T]]) -> T:
        """Run one step of the agent (`make()` starts it). An instruction that arrives meanwhile
        aborts it: the level is rewound, the amendment finishes, and the step starts again with
        the new instructions."""
        while True:
            await self._checkpoint(state)
            await state.amends_idle.wait()
            step = asyncio.create_task(make())
            state.step = step
            try:
                return await step
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if not state.aborting or (task is not None and task.cancelling()):
                    raise  # a stop, not an instruction
                state.aborting = False
                self._rewind_level(state)
            finally:
                state.step = None

    async def _single_turn(self, state: LiveRun):
        """A run without an orchestrator (or without files): one agent turn on a root node."""
        run, emitter = state.run, state.emitter
        await self._checkpoint(state)
        attachments = await self._setup_files(state)
        spec = next((i.text for i in run.instructions if i.kind == "spec"), "")
        run.objectives, candidate = await self.objectives.create_full(
            question=run.question, spec=spec, directives=run.directives,
            attachments=attachments)
        emitter.emit(ObjectivesUpdated, objectives=run.objectives)
        await self._settle_command(state, candidate, attachments)

        root = Node(id="n1", run_id=run.id, type="hypothesis", description=run.question,
                    status="running",
                    version=state.workspace.info.applied_version if state.workspace else None)
        state.nodes.append(root)
        emitter.emit(NodeCreated, node=root)
        emitter.emit(Activity, message="The agent is working on the question.", node_id=root.id)
        emitter.emit(NodeUpdated, node=root, change="running")
        self._boundary(state)  # level 0 created

        result = await self._step(state, lambda: self.agent.run(
            question=run.question, objectives=run.objectives, instructions=run.instructions,
            directives=run.directives, runner=self._runner(state, root)))
        root.tool_calls = {"hypothesis": len(result.records)} if result.records else {}
        return root, result

    async def _run(self, state: LiveRun) -> None:
        run, emitter, nodes = state.run, state.emitter, state.nodes
        started = time.time()
        try:
            single = None
            with self._scopes(run.id):
                if self.orchestrator is not None and run.paths:
                    await self.orchestrator.run(self, state)
                else:
                    single = await self._single_turn(state)
                await self._checkpoint(state)
                await state.amends_idle.wait()  # let a queued amendment finish first

            if single is not None:
                root, result = single
                root.status = "done"
                root.decided_by = "agent"
                root.result = result.reply.answer
                root.tokens = TokenUsage(agent=result.tokens.total)
                emitter.emit(NodeUpdated, node=root, change="done")
                self._boundary(state)  # level 0 completed
                run.final_answer = result.reply.answer
            run.status = "done"
            run.paused = False
            run.totals.tokens = TokenUsage(agent=sum(n.tokens.agent for n in nodes),
                                           scorer=sum(n.tokens.scorer for n in nodes))
            run.totals.nodes_total = len(nodes)
            run.totals.nodes_parked = sum(n.status == "parked" for n in nodes)
            run.totals.experiments_run = sum(n.experiment is not None for n in nodes)
            run.totals.elapsed_s = round(time.time() - started, 2)
            emitter.emit(RunCompleted, run=run)
        except (LLMCancelled, asyncio.CancelledError):
            log.info("run %s was stopped", run.id)  # stop() saves the tree and the final event
            return
        except Exception as e:
            log.exception("run %s failed", run.id)
            self._fail(state, str(e))
            return
        self.store.save_snapshot(state.snapshot())
