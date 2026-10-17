"""File helpers shared by the stores."""

from __future__ import annotations

from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` (creating its folder) so a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)
