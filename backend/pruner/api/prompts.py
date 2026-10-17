"""The prompt templates the backend sends to the LLM (read-only)."""

from fastapi import APIRouter, HTTPException

from pruner.core import prompts
from pruner.core.models import PromptInfo

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _info(name: str, text: str) -> PromptInfo:
    return PromptInfo(name=name, text=text, placeholders=prompts.placeholders(text))


@router.get("")
async def list_prompts() -> list[PromptInfo]:
    return [_info(n, prompts.read_prompt(n) or "") for n in prompts.list_prompts()]


@router.get("/{name}")
async def get_prompt(name: str) -> PromptInfo:
    text = prompts.read_prompt(name)
    if text is None:
        raise HTTPException(status_code=404, detail=f"prompt {name} not found")
    return _info(name, text)
