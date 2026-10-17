"""Which of the user's files a run may touch.

The user gives server paths. A folder means any file under it may be changed; a listed file means
only that file. The run's root is the folder (or, for several paths, their common folder); every
path the agent names is relative to it. safe_rel() makes sure such a path can never point outside
the root, also through a symlink.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Never listed, never sent to the model as code context (noise or private), never editable.
SKIP_DIRS = frozenset({".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
                       ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".idea",
                       ".DS_Store"})
SECRET_PATTERNS = (".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "*.p12",
                   "*.pfx", ".netrc", ".npmrc", ".pypirc")
MAX_FILES = 2000  # files listed per run
MAX_FILE_BYTES = 2_000_000  # larger files are not backed up or edited


class PathError(ValueError):
    pass


def is_secret(rel: str) -> bool:
    name = PurePosixPath(rel).name
    return any(fnmatch.fnmatch(name, p) for p in SECRET_PATTERNS)


@dataclass(frozen=True)
class Roots:
    root: Path  # absolute, resolved; the command runs here
    editable_dirs: tuple[str, ...]  # relative to root, posix; "" means the whole root
    editable_files: tuple[str, ...]

    def is_editable(self, rel: str) -> bool:
        if is_secret(rel) or any(part in SKIP_DIRS for part in PurePosixPath(rel).parts):
            return False
        if rel in self.editable_files:
            return True
        return any(d == "" or rel == d or rel.startswith(d + "/") for d in self.editable_dirs)


def resolve_paths(paths: list[str]) -> Roots:
    """The run's root and editable set from the user's paths (absolute, existing)."""
    if not paths:
        raise PathError("no paths given")
    real = [Path(os.path.realpath(p)) for p in paths]
    for p in real:
        if not p.exists():
            raise PathError(f"{p} does not exist")
    folders = [p if p.is_dir() else p.parent for p in real]
    root = Path(os.path.commonpath([str(f) for f in folders]))
    dirs, files = [], []
    for p in real:
        rel = p.relative_to(root).as_posix()
        if p.is_dir():
            dirs.append("" if rel == "." else rel)
        else:
            files.append(rel)
    return Roots(root=root, editable_dirs=tuple(dict.fromkeys(dirs)),
                 editable_files=tuple(dict.fromkeys(files)))


def safe_rel(roots: Roots, path: str) -> str:
    """`path` (relative to the root, or absolute inside it) as a clean posix path relative to the
    root. PathError if it is empty, contains NUL, or leads outside the root (`..`, an absolute
    path elsewhere, or a symlink that points out)."""
    if not path or "\x00" in path:
        raise PathError("empty path" if not path else "path contains a NUL byte")
    candidate = Path(path) if os.path.isabs(path) else roots.root / path
    resolved = Path(os.path.realpath(candidate))
    try:
        rel = resolved.relative_to(roots.root)
    except ValueError:
        raise PathError(f"{path} is outside the run's files ({roots.root})") from None
    text = rel.as_posix()
    if text in ("", "."):
        raise PathError(f"{path} is the root folder, not a file")
    return text


def list_editable(roots: Roots) -> list[str]:
    """Every editable file (relative, sorted), skipping SKIP_DIRS, secrets, symlinked folders and
    oversized files; at most MAX_FILES."""
    out: set[str] = {f for f in roots.editable_files
                     if (roots.root / f).is_file() and roots.is_editable(f)}
    for d in roots.editable_dirs:
        base = roots.root / d
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(n for n in dirnames if n not in SKIP_DIRS
                                 and not os.path.islink(os.path.join(dirpath, n)))
            for name in sorted(filenames):
                full = Path(dirpath) / name
                if full.is_symlink() or not full.is_file():
                    continue
                rel = full.relative_to(roots.root).as_posix()
                if roots.is_editable(rel) and full.stat().st_size <= MAX_FILE_BYTES:
                    out.add(rel)
                if len(out) >= MAX_FILES:
                    return sorted(out)
    return sorted(out)
