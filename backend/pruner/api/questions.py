"""P1: targeted questions the agent routes to a specific person."""

from fastapi import APIRouter

from ..models import AnswerRequest, Question
from .common import not_implemented

router = APIRouter(prefix="/runs/{run_id}/questions", tags=["questions"])


@router.get("")
async def list_questions(run_id: str) -> list[Question]:
    not_implemented("list_questions")


@router.post("/{question_id}/answer")
async def answer_question(run_id: str, question_id: str, body: AnswerRequest) -> Question:
    """Record the answer, add it to that person's vault, and let the agent continue."""
    not_implemented("answer_question")
