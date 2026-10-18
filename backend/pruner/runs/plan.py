"""The execution plan: the order the work runs in, read by an LLM from the prompt AND the files.

plan() asks the supporting LLM for the steps the user's text lays out (each with the command the
user wrote for it), the one command that runs an experiment, and the input files the text names.
Nothing the LLM says is trusted as is:
- every step's command is checked word for word against what the user wrote (runs/command.py);
  an unverified one is shown as unverified and never runs;
- the run command goes through verify_command (word for word, and its scripts must exist);
- a referenced file only counts if its name is in the user's text; it is "missing" when it is not
  among the attached files (the planner never saw it).
preflight() does the same before a run starts (no backup is made), for the prompt bar.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM
from pruner.core.models import Directive, ExecutionPlan, PlanStep, RunCommand
from pruner.runs.command import clean_candidate, find_source, has_placeholder, verify_command
from pruner.runs.objectives import render_attachments
from pruner.workspace.paths import PathError, Roots, resolve_paths, safe_rel
from pruner.workspace.workspace import attachments_text, read_from_disk

MAX_STEPS = 12


class StepDraft(BaseModel):
    command: str | None = None
    purpose: str = ""
    kind: Literal["setup", "experiment", "check", "record"] = "setup"


class PlanDraft(BaseModel):
    """What the LLM returns (unverified)."""

    steps: list[StepDraft] = Field(default_factory=list)
    run_command: str | None = None
    number_placeholder: str | None = None
    result_hint: str | None = None
    timeout_s: float | None = None
    referenced_files: list[str] = Field(default_factory=list)


def _norm(path: str) -> str:
    return path.strip().strip("`'\"").strip().removeprefix("./")


def missing_files(referenced: Sequence[str], sources: Mapping[str, str], roots: Roots) -> list[str]:
    """The referenced input files that are named in the user's text but not attached."""
    everything = "\n".join(sources.values())
    out: list[str] = []
    for name in dict.fromkeys(_norm(r) for r in referenced):
        if not name or name.endswith("/") or name not in everything:
            continue  # a folder, or a name the LLM made up
        try:
            rel = safe_rel(roots, name)
        except PathError:
            continue  # outside the run's root: not a file the run could be given
        if rel and rel != "." and not roots.is_editable(rel):
            out.append(rel)
    return out


class Planner:
    def __init__(self, llm: LLM, cfg: Config | None = None) -> None:
        self.llm = llm
        self.cfg = cfg or get_config()

    async def draft(self, *, question: str, spec: str, attachments: Mapping[str, str],
                    directives: Sequence[Directive | str] = ()) -> PlanDraft:
        given = "\n\n".join(p for p in (spec.strip(), prompts.render_directives(directives)) if p)
        out = await self.llm.generate(
            PlanDraft, prompts.render("execution_plan", question=question,
                                      spec=given or "(none)",
                                      attached=", ".join(attachments) or "(none)",
                                      attachments=render_attachments(attachments)),
            model=self.cfg.fast_model, purpose="plan")
        return out.value

    async def plan(self, *, question: str, spec: str, attachments: Mapping[str, str],
                   sources: Mapping[str, str], roots: Roots,
                   directives: Sequence[Directive | str] = (),
                   ) -> tuple[ExecutionPlan, RunCommand | None]:
        """The checked plan, and the run command if it could be verified (`sources`: name ->
        the user's texts the commands may be quoted from, as in verify_command)."""
        draft = await self.draft(question=question, spec=spec, attachments=attachments,
                                 directives=directives)
        return check(draft, sources, roots)

    async def preflight(self, *, question: str, spec: str, paths: Sequence[str],
                        directives: Sequence[Directive | str] = ()) -> ExecutionPlan:
        """The plan for a run that has not started: the files are read from disk."""
        relative = [p for p in paths if not os.path.isabs(p)]
        if relative:
            raise PathError(f"{relative[0]} is not an absolute path")
        roots = await asyncio.to_thread(resolve_paths, list(paths))  # PathError if missing
        attachments = await asyncio.to_thread(
            attachments_text, roots, lambda rel: read_from_disk(roots, rel))
        sources = {"question": question, **({"spec": spec} if spec.strip() else {}),
                   **attachments}
        out, _ = await self.plan(question=question, spec=spec, attachments=attachments,
                                 sources=sources, roots=roots, directives=directives)
        return out


def _written(number: float, sources: Mapping[str, str]) -> bool:
    """Whether `number` appears as a whole number in the user's text: 300 in "300 seconds", not
    in "3000" or "1.300" (60.0 is looked for as "60")."""
    text = f"{number:f}".rstrip("0").rstrip(".")
    return re.search(rf"(?<![\d.]){re.escape(text)}(?![\d]|\.\d)",
                     "\n".join(sources.values())) is not None


def check(draft: PlanDraft, sources: Mapping[str, str],
          roots: Roots) -> tuple[ExecutionPlan, RunCommand | None]:
    """The draft with each command checked against the user's text, the missing files, and the
    run command if it is verified."""
    steps = []
    for s in draft.steps[:MAX_STEPS]:
        text = clean_candidate(s.command) if s.command and s.command.strip() else None
        steps.append(PlanStep(command=text, purpose=" ".join(s.purpose.split()), kind=s.kind,
                              verified=bool(text and find_source(text, sources))))
    command, why = verify_command(draft.run_command, sources, roots.root,
                                  result_hint=draft.result_hint)
    if command is not None:
        placeholder = (draft.number_placeholder or "").strip()
        if placeholder and has_placeholder(command.text, placeholder):
            command.number_placeholder = placeholder
        if draft.timeout_s and draft.timeout_s > 0 and _written(draft.timeout_s, sources):
            command.timeout_s = float(draft.timeout_s)  # only a limit the user actually wrote
    plan = ExecutionPlan(steps=steps, run_command=command.text if command else None,
                         command_known=command is not None, why=why,
                         missing_files=missing_files(draft.referenced_files, sources, roots))
    return plan, command
