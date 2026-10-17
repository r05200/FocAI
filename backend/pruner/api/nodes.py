"""Human controls on tree nodes. Each action returns the updated node; the same change also
arrives on the run's event stream (node_updated), so every open client stays in sync."""

from fastapi import APIRouter

from pruner.api.common import not_implemented
from pruner.core.models import Node

router = APIRouter(prefix="/runs/{run_id}/nodes/{node_id}", tags=["nodes"])


@router.post("/keep")
async def keep_node(run_id: str, node_id: str) -> Node:
    """Force a branch to stay (overrides an agent park, or confirms a borderline keep)."""
    not_implemented("keep_node")


@router.post("/park")
async def park_node(run_id: str, node_id: str) -> Node:
    """Park a branch by hand (restorable); also recorded as a dead end for later prompts."""
    not_implemented("park_node")


@router.post("/restore")
async def restore_node(run_id: str, node_id: str) -> Node:
    """Restore a parked branch; the agent continues from its path to the root.
    Also writes a correction item to the vault."""
    not_implemented("restore_node")
