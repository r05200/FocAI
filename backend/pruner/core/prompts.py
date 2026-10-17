"""Load prompt templates from prompts/<name>.md and fill {{placeholders}}.

{{double braces}} are used so prompts can contain literal JSON braces without escaping.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pruner.core.config import get_config
from pruner.core.models import DeadEnd, Directive, Instruction, Objective

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def list_prompts() -> list[str]:
    """Names of the templates in prompts/ (file stems), sorted."""
    return sorted(p.stem for p in get_config().prompts_dir.glob("*.md") if p.stem != "README")


def read_prompt(name: str) -> str | None:
    """A template's raw text, or None if there is no such prompt. Only names from
    list_prompts() are accepted, so a name can never point outside the prompts folder."""
    if name not in list_prompts():
        return None
    return (get_config().prompts_dir / f"{name}.md").read_text()


def placeholders(template: str) -> list[str]:
    return sorted(set(_PLACEHOLDER.findall(template)))


def render(name: str, **values: object) -> str:
    template = (get_config().prompts_dir / f"{name}.md").read_text()
    wanted = set(_PLACEHOLDER.findall(template))
    missing, extra = wanted - values.keys(), values.keys() - wanted
    if missing or extra:
        raise KeyError(f"prompt {name!r}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), template)


def render_directives(directives: Sequence[Directive | str]) -> str:
    """Directives (stored ones, or plain texts sent by the frontend) as a prompt block; empty
    string if there are none."""
    texts = [d if isinstance(d, str) else d.text for d in directives]
    texts = [t.strip() for t in texts if t.strip()]
    return "Standing directives from the user:\n" + "\n".join(f"- {t}" for t in texts) \
        if texts else ""


def render_instructions(instructions: Sequence[Instruction],
                        directives: Sequence[Directive | str] = ()) -> str:
    """The research spec, later instructions, then the person's standing directives, for the
    {{instructions}} placeholder."""
    spec = [i.text for i in instructions if i.kind == "spec"]
    steer = [i.text for i in instructions if i.kind == "steer"]
    block = render_directives(directives)
    if not spec and not steer and not block:
        return "(none)"
    parts = [f"Research specs:\n{chr(10).join(spec)}" if spec else ""]
    if steer:
        parts.append("Further instructions from the user (later ones take priority):\n"
                     + "\n".join(f"{n}. {t}" for n, t in enumerate(steer, 1)))
    parts.append(block)
    return "\n\n".join(p for p in parts if p)


def render_objectives(objectives: Sequence[Objective]) -> str:
    return "\n".join(f"{c.id}: {c.text}" for c in objectives) or "(none)"


def render_dead_ends(dead_ends: Sequence[DeadEnd]) -> str:
    return "\n".join(f"- {d.description} ({d.reason})" for d in dead_ends) or "(none)"
