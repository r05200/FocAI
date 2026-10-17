"""Replay mode: stream a saved run as a live-demo fallback (no LLM calls)."""

from fastapi import APIRouter, Query

from .common import SSE_RESPONSES, not_implemented

router = APIRouter(prefix="/replays", tags=["replays"])


@router.get("")
async def list_replays() -> list[str]:
    """Names of the saved runs in data/replays/."""
    not_implemented("list_replays")


@router.get("/{name}/events", responses=SSE_RESPONSES)
async def stream_replay(
    name: str,
    speed: float = Query(1.0, gt=0, description="Playback speed multiplier."),
):
    """Re-send a saved run's events with their original timing divided by `speed`."""
    not_implemented("stream_replay")
