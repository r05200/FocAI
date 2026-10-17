"""Starting, listing and streaming runs."""

from fastapi import APIRouter, Query

from ..models import Run, RunSnapshot, StartRunRequest
from .common import SSE_RESPONSES, not_implemented

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", status_code=202)
async def start_run(body: StartRunRequest) -> Run:
    """Create a run and start the agent in the background. Follow it via the events stream."""
    not_implemented("start_run")


@router.get("")
async def list_runs() -> list[Run]:
    not_implemented("list_runs")


@router.get("/{run_id}")
async def get_run(run_id: str) -> RunSnapshot:
    """Full current state, for page reloads. Live changes come from the events stream."""
    not_implemented("get_run")


@router.get("/{run_id}/events", responses=SSE_RESPONSES)
async def stream_run_events(
    run_id: str,
    after: int = Query(0, ge=0, description="Only send events with seq greater than this."),
):
    """SSE stream of the run's events. Replays history after `after`, then goes live."""
    not_implemented("stream_run_events")
