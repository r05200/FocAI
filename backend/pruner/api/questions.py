"""Questions a run asks a person. Today: the experiment command, when the user's prompt did not
contain one the run could verify (purpose "command"). Answering it lets the run continue."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from pruner.api.deps import get_run_manager, get_run_store
from pruner.core.models import AnswerRequest, Question
from pruner.runs.manager import QuestionClosed, RunManager, RunNotRunning
from pruner.runs.store import RunStore

router = APIRouter(prefix="/runs/{run_id}/questions", tags=["questions"])

Store = Annotated[RunStore, Depends(get_run_store)]
Manager = Annotated[RunManager, Depends(get_run_manager)]


@router.get("")
async def list_questions(run_id: str, store: Store) -> list[Question]:
    snapshot = store.snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run not found")
    return snapshot.questions


@router.post("/{question_id}/answer")
async def answer_question(run_id: str, question_id: str, body: AnswerRequest,
                          manager: Manager) -> Question:
    """Record the answer. For the "command" question the answer becomes the run's experiment
    command exactly as typed, and the run carries on. 404 if the run or question is unknown, 409
    if the run finished or the question was already answered, 422 for an empty answer."""
    try:
        return await manager.answer(run_id, question_id, body.answer)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="run or question not found") from e
    except (RunNotRunning, QuestionClosed) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
