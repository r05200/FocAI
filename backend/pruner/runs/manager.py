"""Starts runs, keeps them going in the background, and handles prompts sent mid-run.

start() turns a prompt (StartRunRequest) into a Run, saves its first event, and spins up the
agent as an asyncio task. The task:
  1. writes the run's objectives from the spec (supporting LLM),
  2. runs the agent on its own LLM, shown in the tree as a root node,
  3. ends the run: run_completed with the final answer, or run_failed on an error.

instruct() handles a later prompt (InstructionRequest): it records the instruction, then in the
background amends the objectives and, if any objective was added, runs the amend-objectives agent
over the tree (re-rating nodes and requesting forks where every branch is low).

Every step is appended to the run's event log (RunStore) and the snapshot is saved. A run's live
state (run, nodes) is shared by its tasks, so a mid-run instruction and the agent see the same
objects. All LLM calls happen inside `llm.scope(run_id)`, so the stop route can cancel them; a
stopped run is ended by the stop route (it saves the final event), so tasks just exit quietly.

Not built yet: pushing events to connected clients (the SSE stream), more than one agent turn,
and acting on fork requests.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import ExitStack
from dataclasses import dataclass, field

from pruner.agent.agent import Agent
from pruner.agent.amend import AmendObjectivesAgent
from pruner.core.config import Config, get_config
from pruner.core.events import (
    Activity,
    EventBase,
    InstructionAdded,
    NodeCreated,
    NodeUpdated,
    ObjectivesUpdated,
    RunCompleted,
    RunFailed,
    RunStarted,
)
from pruner.core.llm import LLMCancelled, LLMError
from pruner.core.models import (
    Caps,
    DeadEnd,
    Instruction,
    InstructionRequest,
    Node,
    Question,
    Run,
    RunSnapshot,
    StartRunRequest,
    TokenUsage,
)
from pruner.runs.objectives import ObjectiveMaker
from pruner.runs.store import RunStore

log = logging.getLogger(__name__)


class Emitter:
    """Numbers a run's events (from 1) and appends them to the store."""

    def __init__(self, store: RunStore, run_id: str, last_seq: int = 0) -> None:
        self.store, self.run_id, self.seq = store, run_id, last_seq

    def emit(self, cls: type[EventBase], **fields) -> EventBase:
        self.seq += 1
        event = cls(seq=self.seq, run_id=self.run_id, **fields)
        self.store.append_event(event)  # type: ignore[arg-type]
        return event


@dataclass
class LiveRun:
    """A run's state while something is working on it, shared by all of its tasks."""

    run: Run
    emitter: Emitter
    nodes: list[Node] = field(default_factory=list)
    dead_ends: list[DeadEnd] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    tasks: set[asyncio.Task] = field(default_factory=set)

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot(run=self.run, nodes=self.nodes, dead_ends=self.dead_ends,
                           questions=self.questions)


class RunManager:
    def __init__(self, store: RunStore, agent: Agent, objectives: ObjectiveMaker,
                 cfg: Config | None = None, *,
                 amender: AmendObjectivesAgent | None = None) -> None:
        self.store, self.agent, self.objectives, self.amender = store, agent, objectives, amender
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
            mode=req.mode,
            caps=Caps(max_depth=self.cfg.max_depth, branching=self.cfg.branching,
                      node_budget=self.cfg.node_budget),
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

    def _state(self, run_id: str) -> LiveRun:
        """The run's live state, or one loaded from disk. KeyError if there is no such run."""
        if run_id in self._live:
            return self._live[run_id]
        snap = self.store.snapshot(run_id)
        if snap is None:
            raise KeyError(run_id)
        state = LiveRun(run=snap.run, emitter=Emitter(self.store, run_id,
                                                      self.store.last_seq(run_id)),
                        nodes=list(snap.nodes), dead_ends=list(snap.dead_ends),
                        questions=list(snap.questions))
        self._live[run_id] = state
        return state

    def _scopes(self, run_id: str) -> ExitStack:
        """Tag every LLM call made for this run with its id, so the stop route reaches them."""
        llms = [self.objectives.llm, self.agent.llm]
        if self.amender is not None:
            llms.append(self.amender.scorer.llm)
        stack = ExitStack()
        for llm in llms:
            stack.enter_context(llm.scope(run_id))
        return stack

    async def start(self, req: StartRunRequest) -> Run:
        """Create the run, record it, and start the agent in the background."""
        run = self._new_run(req)
        state = LiveRun(run=run.model_copy(deep=True), emitter=Emitter(self.store, run.id))
        self._live[run.id] = state
        state.emitter.emit(RunStarted, run=run)
        self.store.save_snapshot(RunSnapshot(run=run, nodes=[]))  # so it shows up as running
        self._spawn(state, self._run(state))
        return run

    async def instruct(self, run_id: str, req: InstructionRequest) -> Instruction:
        """Record a mid-run prompt now; amend the objectives and re-check the tree in the
        background. KeyError if the run is unknown."""
        state = self._state(run_id)
        instruction = Instruction(kind="steer", text=req.text.strip())
        state.run.instructions.append(instruction)
        if req.directives is not None:
            state.run.directives = list(req.directives)
        state.emitter.emit(InstructionAdded, instruction=instruction)
        self.store.save_snapshot(state.snapshot())
        self._spawn(state, self._amend(state, instruction))
        return instruction

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
        await asyncio.gather(*tasks, return_exceptions=True)
        return True

    async def wait(self, run_id: str) -> None:
        """Wait until every task of the run is finished (used by tests and shutdown)."""
        while (state := self._live.get(run_id)) and state.tasks:
            await asyncio.gather(*list(state.tasks), return_exceptions=True)

    async def _amend(self, state: LiveRun, instruction: Instruction) -> None:
        run, emitter = state.run, state.emitter
        try:
            with self._scopes(run.id):
                new = await self.objectives.amend(run.objectives, instruction,
                                                  question=run.question, directives=run.directives)
                if not new:
                    emitter.emit(Activity, message="The instruction added no new objectives.")
                    return
                run.objectives = [*run.objectives, *new]
                emitter.emit(ObjectivesUpdated, objectives=run.objectives)
                if self.amender is None or not state.nodes:
                    return
                result = await self.amender.run(run, state.nodes)
            by_id = {n.id: n for n in state.nodes}
            for s in result.rated:
                emitter.emit(NodeUpdated, node=by_id[s.node_id], change="scored")
            for fork in result.forks:
                emitter.emit(Activity, node_id=fork.node_id,
                             message=f"Backtracking: fork requested here. {fork.reason}")
        except (LLMCancelled, asyncio.CancelledError):
            log.info("amendment for run %s was stopped", run.id)
            return
        except (LLMError, ValueError, OSError) as e:
            log.exception("amendment for run %s failed", run.id)
            emitter.emit(Activity, message=f"Could not apply the instruction: {e}")
        finally:
            self.store.save_snapshot(state.snapshot())

    async def _run(self, state: LiveRun) -> None:
        run, emitter, nodes = state.run, state.emitter, state.nodes
        started = time.time()
        try:
            with self._scopes(run.id):
                spec = next((i.text for i in run.instructions if i.kind == "spec"), "")
                run.objectives = await self.objectives.create(
                    question=run.question, spec=spec, directives=run.directives)
                emitter.emit(ObjectivesUpdated, objectives=run.objectives)

                root = Node(run_id=run.id, type="hypothesis", description=run.question,
                            status="running")
                nodes.append(root)
                emitter.emit(NodeCreated, node=root)
                emitter.emit(Activity, message="The agent is working on the question.",
                             node_id=root.id)
                emitter.emit(NodeUpdated, node=root, change="running")

                result = await self.agent.run(
                    question=run.question, objectives=run.objectives,
                    instructions=run.instructions, directives=run.directives)

            root.status = "done"
            root.decided_by = "agent"
            root.result = result.reply.answer
            root.tokens = TokenUsage(agent=result.tokens.total)
            emitter.emit(NodeUpdated, node=root, change="done")
            run.final_answer = result.reply.answer
            run.status = "done"
            run.totals.tokens = root.tokens
            run.totals.nodes_total = len(nodes)
            run.totals.elapsed_s = round(time.time() - started, 2)
            emitter.emit(RunCompleted, run=run)
        except (LLMCancelled, asyncio.CancelledError):
            log.info("run %s was stopped", run.id)  # the stop route saves the final event
            return
        except (LLMError, ValueError, OSError) as e:
            log.exception("run %s failed", run.id)
            run.status = "failed"
            emitter.emit(RunFailed, error=str(e))
        self.store.save_snapshot(state.snapshot())
