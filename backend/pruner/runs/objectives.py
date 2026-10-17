"""Objectives: the run's checklist, as short point-form goals written by an LLM.

- create(): when a run starts, the original specs (and question) become the first objectives.
- amend(): whenever the user sends a further instruction, it is turned into NEW objectives that
  are appended. Existing objectives are never rewritten or removed, and repeats are dropped.

The scorers judge against these (Node.criteria_progress holds the objective ids a result
advances). Emitting ObjectivesUpdated with the full list is left to the agent loop.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel, Field

from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM
from pruner.core.models import Directive, Instruction, Objective

MAX_ON_CREATE = 6
MAX_ON_AMEND = 3


class ObjectiveDraft(BaseModel):
    """What the LLM returns: plain strings, numbered and attributed by our code."""

    objectives: list[str] = Field(default_factory=list)


def _clean(text: str) -> str:
    return " ".join(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", text).split())


def _next_id(existing: Sequence[Objective]) -> int:
    numbers = [int(m.group(1)) for o in existing if (m := re.fullmatch(r"o(\d+)", o.id))]
    return max(numbers, default=0) + 1


class ObjectiveMaker:
    def __init__(self, llm: LLM, cfg: Config | None = None) -> None:
        self.llm = llm
        self.cfg = cfg or get_config()

    async def _draft(self, name: str, purpose: str, **values: str) -> list[str]:
        out = await self.llm.generate(ObjectiveDraft, prompts.render(name, **values),
                                      model=self.cfg.fast_model, purpose=purpose)
        return [t for t in map(_clean, out.value.objectives) if t]

    def _number(self, texts: Sequence[str], existing: Sequence[Objective], source: str,
                limit: int) -> list[Objective]:
        seen = {o.text.casefold() for o in existing}
        fresh: list[str] = []
        for t in texts:
            if t.casefold() not in seen:
                seen.add(t.casefold())
                fresh.append(t)
        start = _next_id(existing)
        return [Objective(id=f"o{start + n}", text=t, source=source)
                for n, t in enumerate(fresh[:limit])]

    async def create(self, *, question: str, spec: str = "",
                     directives: Sequence[Directive | str] = ()) -> list[Objective]:
        """The run's first objectives, from the original specs, with any directives the
        frontend sent appended to them. If the LLM returns nothing, the question itself becomes
        the only objective, so a run never starts with none."""
        given = "\n\n".join(p for p in (spec.strip(), prompts.render_directives(directives)) if p)
        texts = await self._draft("objectives", "objectives", question=question,
                                  spec=given or "(none; use the question)")
        return self._number(texts, [], "spec", MAX_ON_CREATE) or [
            Objective(id="o1", text=_clean(question), source="spec")]

    async def amend(self, existing: Sequence[Objective], instruction: Instruction, *,
                    question: str = "",
                    directives: Sequence[Directive | str] = ()) -> list[Objective]:
        """The NEW objectives an instruction adds (possibly none), to append to `existing`.
        Directives the frontend sent are appended to the instruction text."""
        given = "\n\n".join(
            p for p in (instruction.text, prompts.render_directives(directives)) if p)
        texts = await self._draft(
            "objectives_amend", "objectives", question=question or "(not given)",
            objectives=prompts.render_objectives(existing), instruction=given)
        return self._number(texts, existing, instruction.id, MAX_ON_AMEND)
