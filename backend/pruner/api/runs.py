"""Starting, listing and streaming runs."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from pruner.api.common import SSE_RESPONSES, not_implemented
from pruner.api.deps import get_run_store
from pruner.core.models import Instruction, InstructionRequest, Run, RunSnapshot, StartRunRequest
from pruner.runs.store import RunStore

router = APIRouter(prefix="/runs", tags=["runs"])

Store = Annotated[RunStore, Depends(get_run_store)]


@router.post("", status_code=202)
async def start_run(body: StartRunRequest) -> Run:
    """Create a run and start the agent in the background. Follow it via the events stream."""
    not_implemented("start_run")


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
async def add_instruction(run_id: str, body: InstructionRequest) -> Instruction:
    """Append a steering instruction to the run's spec. The agent and scorers see it from the
    next step on; an instruction_added event is sent on the stream."""
    not_implemented("add_instruction")


@router.get("/{run_id}/events", responses=SSE_RESPONSES)
async def stream_run_events(
    run_id: str,
    after: int = Query(0, ge=0, description="Only send events with seq greater than this."),
):
    """SSE stream of the run's events. Replays history after `after`, then goes live."""
    not_implemented("stream_run_events")
