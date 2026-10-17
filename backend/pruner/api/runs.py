"""Starting, listing and streaming runs."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from pruner.api.common import SSE_HEADERS, SSE_RESPONSES
from pruner.api.deps import get_agent_llm, get_run_manager, get_run_store, get_supporting_llm
from pruner.core.llm import LLM
from pruner.core.models import (
    ForkRequest,
    Instruction,
    InstructionRequest,
    InstructionToggle,
    ManualRequest,
    PauseResult,
    Run,
    RunSnapshot,
    StartRunRequest,
    StopResult,
)
from pruner.runs.manager import (
    InstructionLocked,
    ObjectivesNotReady,
    PathLocked,
    RunManager,
    RunNotRunning,
)
from pruner.runs.store import RunStore
from pruner.runs.stream import run_events

router = APIRouter(prefix="/runs", tags=["runs"])

Store = Annotated[RunStore, Depends(get_run_store)]
Manager = Annotated[RunManager, Depends(get_run_manager)]


@router.post("", status_code=202)
async def start_run(body: StartRunRequest, manager: Manager) -> Run:
    """Send the prompt: create the run and spin up the agent in the background. The run's
    objectives are written from `spec` first, then the agent works on `question`. Follow it live
    with GET /runs/{id}/events, or poll GET /runs/{id}. With `paths` the run edits those files
    and runs the user's command; without, it is a research run that searches for resources.
    409 if another running run already holds one of the `paths` (or a folder around or inside
    it): paths are locked until that run finishes or is stopped."""
    try:
        return await manager.start(body)
    except PathLocked as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("")
async def list_runs(store: Store) -> list[Run]:
    """Every saved run, newest first (historical runs included)."""
    return store.list()


@router.get("/{run_id}")
async def get_run(run_id: str, store: Store) -> RunSnapshot:
    """Full current state, for page reloads and for reopening a historical run. Live changes
    come from the events stream."""
    snapshot = store.snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run not found")
    return snapshot


@router.post("/{run_id}/instructions", status_code=202)
async def add_instruction(run_id: str, body: InstructionRequest, manager: Manager) -> Instruction:
    """Send a further prompt to a run. It is recorded at once (instruction_added). Then, in the
    background, it is turned into new objectives (objectives_updated) and, if any were added, the
    amend-objectives agent re-rates the tree from the root (node_updated "scored") and requests a
    fork wherever every branch under a node scored low (an activity line; GET /runs/{id}/forks).
    On a run with files the whole tree is then re-rated for the new direction in one call and 2-3
    suggestions are offered (suggestions_ready; forks are among them).
    `directives`, when given, replaces the run's directive list.

    409 while the objectives are still being written, and once the run has finished (done, failed
    or stopped). A paused run queues the instruction; a running step is aborted and started again
    after the amendment."""
    try:
        return await manager.instruct(run_id, body)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="run not found") from e
    except (RunNotRunning, ObjectivesNotReady) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.patch("/{run_id}/instructions/{instruction_id}")
async def toggle_instruction(run_id: str, instruction_id: str, body: InstructionToggle,
                             manager: Manager) -> Instruction:
    """Turn a steering instruction (a chip) on or off. While off it is left out of every prompt.
    On a run with files the tree is then re-rated in one call (node_updated "scored" / "parked" /
    "restored") and new suggestions are offered (suggestions_ready); the step in flight is not
    aborted. The run's instructions arrive in run_updated. 404 unknown run or instruction, 409 if
    the run finished, its objectives are not written yet, or it is the research spec."""
    try:
        return await manager.toggle_instruction(run_id, instruction_id, body.active)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="run or instruction not found") from e
    except (RunNotRunning, ObjectivesNotReady, InstructionLocked) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/{run_id}/manual")
async def set_manual_mode(run_id: str, body: ManualRequest, manager: Manager) -> Run:
    """Turn manual mode on or off; returns the run. On: before each experiment the run waits for
    a person to choose which proposed hypothesis to pursue. The nodes whose proposals wait get
    `awaiting_choice: true` (node_updated "awaiting") and the run gets `awaiting: "choice"`
    (run_updated). POST .../nodes/{node_id}/keep on a waiting hypothesis runs it next; .../park
    drops it; confirming a "run" suggestion picks it too. Off: the agent chooses again, at once if
    the run was waiting. 404 if the run is unknown, 409 if it already finished."""
    try:
        return await manager.set_manual(run_id, body.manual)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="run not found") from e
    except RunNotRunning as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/{run_id}/pause", status_code=202)
async def pause_run(run_id: str, manager: Manager) -> PauseResult:
    """Hold the run: calls already in flight finish, but its next step (and any step an
    instruction starts) waits until /resume. `paused` becomes true on the run. 404 if the run is
    unknown, 409 if it already finished. Pausing a paused run is fine."""
    return await _hold(manager.pause, run_id)


@router.post("/{run_id}/resume", status_code=202)
async def resume_run(run_id: str, manager: Manager) -> PauseResult:
    """Open the gate; the run carries on from where it was. Same errors as /pause."""
    return await _hold(manager.resume, run_id)


async def _hold(call, run_id: str) -> PauseResult:
    try:
        run = await call(run_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="run not found") from e
    except RunNotRunning as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return PauseResult(run_id=run_id, paused=run.paused)


@router.get("/{run_id}/patch", response_class=PlainTextResponse)
async def get_patch(run_id: str, store: Store) -> str:
    """The changes the run left applied to the user's files, as a unified diff from the original
    files (empty if nothing was kept). 404 until the run has finished with files."""
    if store.snapshot(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    patch = store.patch(run_id)
    if patch is None:
        raise HTTPException(status_code=404, detail="this run has no patch (yet)")
    return patch


@router.get("/{run_id}/forks")
async def list_forks(run_id: str, store: Store) -> list[ForkRequest]:
    """Where the amend-objectives agent asked to restart exploration (forking is not built)."""
    if store.snapshot(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return store.forks(run_id)


@router.post("/{run_id}/stop", status_code=202)
async def stop_run(
    run_id: str,
    store: Store,
    manager: Manager,
    agent_llm: Annotated[LLM, Depends(get_agent_llm)],
    supporting_llm: Annotated[LLM, Depends(get_supporting_llm)],
) -> StopResult:
    """Stop the run now. Its LLM calls in flight (agent and supporting) are cancelled (the Gemini
    request is abandoned and the caller gets LLMCancelled) and its later calls are refused, so
    the agent loop cannot start another step. Then a final run_failed event ("Stopped by the
    user") is saved and the run's status becomes "failed". 404 if the run is unknown, 409 if it
    already finished.

    Only calls made inside `llm.scope(run_id)` are affected; other runs and vault ingestion keep
    working."""
    snapshot = store.snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run not found")
    if snapshot.run.status != "running":
        raise HTTPException(status_code=409, detail=f"run already {snapshot.run.status}")
    # The agent and the supporting LLM are separate instances; the run may be using both.
    cancelled = agent_llm.stop(run_id) + supporting_llm.stop(run_id)
    await manager.stop(run_id)  # ends the run's tasks, then saves the tree as it is
    return StopResult(run_id=run_id, cancelled_calls=cancelled)


@router.get("/{run_id}/events", responses=SSE_RESPONSES)
async def stream_run_events(
    run_id: str,
    request: Request,
    store: Store,
    manager: Manager,
    after: int = Query(0, ge=0, description="Only send events with seq greater than this."),
    last_event_id: Annotated[str | None, Header()] = None,
):
    """SSE stream of the run's events: the saved ones with seq greater than `after` (or the
    Last-Event-ID header a reconnecting EventSource sends, whichever is later), then live ones.
    `event:` is the type, `id:` the seq, `data:` the event JSON; a ": ping" comment every 15 s.
    It ends after run_completed or run_failed (at once for a finished run with nothing newer).
    A client that falls far behind is cut off and resumes with Last-Event-ID. 404 if the run is
    unknown."""
    if store.snapshot(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        resume = int(last_event_id) if last_event_id else 0
    except ValueError:
        resume = 0
    return StreamingResponse(
        run_events(store, manager.bus, run_id, max(after, resume),
                   is_disconnected=request.is_disconnected),
        media_type="text/event-stream", headers=SSE_HEADERS)
