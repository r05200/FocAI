"""Human controls on tree nodes. Each action returns the updated node; the same change also
arrives on the run's event stream (node_updated), so every open client stays in sync."""

from fastapi import APIRouter

from ..models import Node
from .common import not_implemented

router = APIRouter(prefix="/runs/{run_id}/nodes/{node_id}", tags=["nodes"])


@router.post("/keep")
async def keep_node(run_id: str, node_id: str) -> Node:
    """Force a branch to stay (overrides an agent prune, or confirms a borderline keep)."""
    not_implemented("keep_node")


@router.post("/prune")
async def prune_node(run_id: str, node_id: str) -> Node:
    """Prune a branch by hand; also recorded as a dead end for later prompts."""
    not_implemented("prune_node")


@router.post("/restore")
async def restore_node(run_id: str, node_id: str) -> Node:
    """Revive a pruned branch; the agent continues from its path to the root.
    Also writes a correction item to the vault."""
    not_implemented("restore_node")
