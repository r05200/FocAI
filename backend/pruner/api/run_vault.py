"""The run vault: what the agent found during one run (ideas and whole-branch findings). It is
separate from the people's vaults; saved as data/runs/<id>/vault.json."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from pruner.api.deps import get_run_store
from pruner.core.models import RunVault
from pruner.runs.store import RunStore

router = APIRouter(prefix="/runs/{run_id}/vault", tags=["runs"])

Store = Annotated[RunStore, Depends(get_run_store)]


def _require_run(store: RunStore, run_id: str) -> None:
    if store.snapshot(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")


@router.get("")
async def get_run_vault(run_id: str, store: Store) -> RunVault:
    _require_run(store, run_id)
    return store.run_vault(run_id) or RunVault(run_id=run_id)


@router.post("", status_code=201)
async def create_run_vault(run_id: str, store: Store) -> RunVault:
    """Create the run's (empty) vault. Idempotent: an existing one comes back as it is. Runs
    started by the backend already have one."""
    _require_run(store, run_id)
    vault = store.run_vault(run_id)
    if vault is None:
        vault = RunVault(run_id=run_id)
        store.save_run_vault(vault)
    return vault
