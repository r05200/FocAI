"""Where a run could continue from: offered after a steering re-rate (2-3 from different
families) or where the amend agent asked for a fork. A person confirms or dismisses each."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from pruner.api.deps import get_run_manager, get_run_store
from pruner.core.models import Suggestion
from pruner.orchestrator.human import IllegalAction
from pruner.runs.manager import RunManager, RunNotRunning, SuggestionClosed
from pruner.runs.store import RunStore

router = APIRouter(prefix="/runs/{run_id}/suggestions", tags=["suggestions"])

Store = Annotated[RunStore, Depends(get_run_store)]
Manager = Annotated[RunManager, Depends(get_run_manager)]


@router.get("")
async def list_suggestions(run_id: str, store: Store) -> list[Suggestion]:
    """Every suggestion the run made, oldest first; the open ones are `status: "open"`."""
    snapshot = store.snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run not found")
    return snapshot.suggestions


@router.post("/{suggestion_id}/confirm")
async def confirm_suggestion(run_id: str, suggestion_id: str, manager: Manager) -> Suggestion:
    """Act on it: "run" runs that node next, "restore" restores it, "expand" and "remeasure"
    propose new hypotheses from it before the next experiment. 404 unknown run or suggestion,
    409 if the run finished, the suggestion was already answered, or it no longer fits (the node
    is no longer waiting, or there is no room under it)."""
    return await _resolve(manager, run_id, suggestion_id, True)


@router.post("/{suggestion_id}/dismiss")
async def dismiss_suggestion(run_id: str, suggestion_id: str, manager: Manager) -> Suggestion:
    """Drop it. Same errors as /confirm."""
    return await _resolve(manager, run_id, suggestion_id, False)


async def _resolve(manager: RunManager, run_id: str, suggestion_id: str,
                   confirm: bool) -> Suggestion:
    try:
        return await manager.resolve_suggestion(run_id, suggestion_id, confirm)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="run or suggestion not found") from e
    except (RunNotRunning, SuggestionClosed, IllegalAction) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
