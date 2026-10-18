"""File helpers shared by the stores."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, text: str | bytes) -> None:
    """Write `text` to `path` (creating its folder) so a reader never sees a half-written file:
    a uniquely named temp file in the same folder (two writers never share one), flushed to disk,
    then renamed over the target. The temp file is removed if anything fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode() if isinstance(text, str) else text
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
