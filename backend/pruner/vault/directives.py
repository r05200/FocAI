"""Directives: standing instructions a person files under the vault's Directives tab.

They live beside the vault but are not vault items: no LLM call, no embedding, no links, no
graph node. data/vaults/_directives.json holds all of them, rewritten atomically on each change.
"""

from __future__ import annotations

import json
from pathlib import Path

from pruner.core.config import Config, get_config
from pruner.core.fs import write_atomic
from pruner.core.models import Directive, DirectiveRequest

DIRECTIVES_FILE = "_directives.json"


class DirectiveStore:
    def __init__(self, directory: Path | None = None, cfg: Config | None = None) -> None:
        self.dir = directory or (cfg or get_config()).vault_dir
        self._path = self.dir / DIRECTIVES_FILE
        self._directives: dict[str, Directive] = {}
        if self._path.exists():
            for raw in json.loads(self._path.read_text()):
                d = Directive.model_validate(raw)
                self._directives[d.id] = d

    def _save(self) -> None:
        write_atomic(self._path, json.dumps(
            [d.model_dump(mode="json") for d in self._directives.values()], separators=(",", ":")))

    def add(self, req: DirectiveRequest) -> Directive:
        directive = Directive(person=req.person, text=req.text.strip())
        self._directives[directive.id] = directive
        self._save()
        return directive

    def list(self, person: str | None = None) -> list[Directive]:
        """Oldest first, optionally only one person's."""
        return sorted((d for d in self._directives.values() if person in (None, d.person)),
                      key=lambda d: d.created_at)

    def delete(self, directive_id: str) -> bool:
        if self._directives.pop(directive_id, None) is None:
            return False
        self._save()
        return True
