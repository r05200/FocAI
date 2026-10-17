"""Load prompt templates from prompts/<name>.md and fill {{placeholders}}.

{{double braces}} are used so prompts can contain literal JSON braces without escaping.
"""

from __future__ import annotations

import re

from .config import get_config

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def render(name: str, **values: object) -> str:
    template = (get_config().prompts_dir / f"{name}.md").read_text()
    wanted = set(_PLACEHOLDER.findall(template))
    missing, extra = wanted - values.keys(), values.keys() - wanted
    if missing or extra:
        raise KeyError(f"prompt {name!r}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), template)
