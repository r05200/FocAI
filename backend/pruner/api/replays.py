"""Replay mode: stream a saved run as a live-demo fallback (no LLM calls). Make one with
`uv run python -m pruner.replay export <run_id> <name>` (see pruner/replay.py)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from pruner.api.common import SSE_HEADERS, SSE_RESPONSES
from pruner.core.config import Config, get_config
from pruner.replay import list_replays, replay_events, replay_stream

router = APIRouter(prefix="/replays", tags=["replays"])

Cfg = Annotated[Config, Depends(get_config)]


@router.get("")
async def list_saved_replays(cfg: Cfg) -> list[str]:
    """Names of the saved replays in data/replays/."""
    return list_replays(cfg)


@router.get("/{name}/events", responses=SSE_RESPONSES)
async def stream_replay(
    name: str,
    cfg: Cfg,
    speed: float = Query(1.0, gt=0, description="Playback speed multiplier."),
):
    """Re-send a saved run's events with their original timing divided by `speed` (each gap is
    capped at 2 s before dividing). The same SSE format as GET /runs/{id}/events. 404 if there
    is no such replay."""
    events = replay_events(name, cfg)
    if events is None:
        raise HTTPException(status_code=404, detail="replay not found")
    return StreamingResponse(replay_stream(events, speed), media_type="text/event-stream",
                             headers=SSE_HEADERS)
