"""Human controls on tree nodes. Each action returns the updated node; the same change also
arrives on the run's event stream (node_updated), so every open client stays in sync."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from pruner.api.common import not_implemented
from pruner.api.deps import get_run_store
from pruner.core.models import LogEntry, Node
from pruner.runs.store import RunStore

router = APIRouter(prefix="/runs/{run_id}/nodes/{node_id}", tags=["nodes"])

Store = Annotated[RunStore, Depends(get_run_store)]


@router.get("/logs")
async def get_node_logs(run_id: str, node_id: str, store: Store) -> list[LogEntry]:
    """Everything logged on a node, oldest first: the agent's tool calls (each with the reason
    it gave) and their results, decisions and errors. 404 if the run or node is unknown."""
    snapshot = store.snapshot(run_id)
    if snapshot is None or all(n.id != node_id for n in snapshot.nodes):
        raise HTTPException(status_code=404, detail="run or node not found")
    return store.logs(run_id, node_id)


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
