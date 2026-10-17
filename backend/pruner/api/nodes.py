"""Human controls on tree nodes. Each action returns the updated node; the same change also
arrives on the run's event stream (node_updated), so every open client stays in sync."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from pruner.api.deps import get_run_manager, get_run_store
from pruner.core.models import HumanAction, LogEntry, Node
from pruner.orchestrator.human import IllegalAction
from pruner.runs.manager import RunManager, RunNotRunning
from pruner.runs.store import RunStore

router = APIRouter(prefix="/runs/{run_id}/nodes/{node_id}", tags=["nodes"])

Store = Annotated[RunStore, Depends(get_run_store)]
Manager = Annotated[RunManager, Depends(get_run_manager)]


@router.get("/logs")
async def get_node_logs(run_id: str, node_id: str, store: Store) -> list[LogEntry]:
    """Everything logged on a node, oldest first: the agent's tool calls (each with the reason
    it gave) and their results, decisions and errors. 404 if the run or node is unknown."""
    snapshot = store.snapshot(run_id)
    if snapshot is None or all(n.id != node_id for n in snapshot.nodes):
        raise HTTPException(status_code=404, detail="run or node not found")
    return store.logs(run_id, node_id)


@router.post("/keep")
async def keep_node(run_id: str, node_id: str, manager: Manager) -> Node:
    """Force a branch to stay: a parked node comes back (to the queue if it never ran), a
    waiting one moves up the queue, and neither re-rates nor the judge can park it later.
    Errors as for /park."""
    return await _act(manager, run_id, node_id, "keep")


@router.post("/park")
async def park_node(run_id: str, node_id: str, manager: Manager) -> Node:
    """Park a branch by hand (restorable); also recorded as a dead end for later prompts, and
    nothing under it runs. On a running node it applies once its step finishes (the node comes
    back unchanged, and node_updated "parked" follows). 404 unknown run or node, 409 if the run
    finished or the action does not fit (the baseline, a failed node)."""
    return await _act(manager, run_id, node_id, "park")


@router.post("/restore")
async def restore_node(run_id: str, node_id: str, manager: Manager) -> Node:
    """Restore a parked branch, with any parked nodes on its path, so the run continues from it:
    back to the queue if it never ran, else new hypotheses from it come before the next
    experiment. Also writes a correction item to the person's vault. 409 if it is not parked."""
    return await _act(manager, run_id, node_id, "restore")


async def _act(manager: RunManager, run_id: str, node_id: str, action: HumanAction) -> Node:
    try:
        return await manager.node_action(run_id, node_id, action)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="run or node not found") from e
    except (RunNotRunning, IllegalAction) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
