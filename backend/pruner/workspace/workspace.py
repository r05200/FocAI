"""The user's files for one run, edited in place, with versions and a baseline backup.

There is no copy and no sandbox: experiments change the real files. What this module adds is the
bookkeeping that makes that safe to undo:

- At the start every editable file is backed up once to <work_dir>/<run_id>/baseline/.
- A code version is a manifest (path -> content hash) over content-addressed blobs, all under
  <work_dir>/<run_id>/. commit_edit() makes a new version from a base version and an Edit in
  memory, so a proposed (or parked) node already has a version without touching the disk.
- apply_version() writes a version to the real files. It compares with what is ON DISK (not with
  its own bookkeeping), so a half-finished apply, or an experiment command that rewrote a tracked
  file, is repaired by the next apply or restore. It never overwrites or deletes a file the run
  does not own: a file that is not in the run's versions, or a run-created file someone changed.
- commit_edit() refuses a new file wherever something already exists on disk (including another
  spelling of an existing name on a case-insensitive filesystem such as macOS's).
- One lock per workspace: a stop that settles the files waits for an apply still running in its
  worker thread instead of racing it.
- patch() is the unified diff from the baseline to a version, for the user to keep or reverse.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path, PurePosixPath

from pruner.core.config import Config, get_config
from pruner.core.fs import write_atomic
from pruner.core.models import DiffStats, Edit, WorkspaceInfo
from pruner.workspace.edits import EditError, apply_edit, diff_stats, unified_diff
from pruner.workspace.paths import (
    MAX_FILE_BYTES,
    PathError,
    Roots,
    list_editable,
    resolve_paths,
    safe_rel,
)

INFO_FILE = "workspace.json"
READ_MAX_BYTES = 400_000  # larger files are not read into prompts


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(data: bytes | None) -> str | None:
    if data is None or b"\x00" in data[:8000]:
        return None  # missing or binary
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class WorkspaceConflict(OSError):
    """A file on disk is in the way and is not the run's to change."""


class Workspace:
    def __init__(self, info: WorkspaceInfo, folder: Path) -> None:
        self.info = info
        self.folder = folder  # <work_dir>/<run_id>
        self.roots = Roots(root=Path(info.root), editable_dirs=tuple(info.editable_dirs),
                           editable_files=tuple(info.editable_files))
        self._lock = threading.RLock()  # one apply / commit at a time (they run in threads)
        self._stats: dict[str, tuple[int, int, str]] = {}  # rel -> (size, mtime_ns, sha)

    # ---- creation and loading

    @classmethod
    def create(cls, run_id: str, paths: list[str], cfg: Config | None = None) -> Workspace:
        """Back up the editable files under `paths` and record the baseline version."""
        cfg = cfg or get_config()
        roots = resolve_paths(paths)
        folder = cfg.work_dir / run_id
        files = list_editable(roots)
        manifest: dict[str, str] = {}
        for rel in files:
            src = roots.root / rel
            data = src.read_bytes()
            manifest[rel] = cls._put_blob(folder, data)
            dest = folder / "baseline" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        version = cls._put_manifest(folder, manifest)
        info = WorkspaceInfo(root=str(roots.root), editable_dirs=list(roots.editable_dirs),
                             editable_files=list(roots.editable_files), files=files,
                             baseline_version=version, applied_version=version)
        ws = cls(info, folder)
        ws._save_info()
        return ws

    @classmethod
    def load(cls, run_id: str, cfg: Config | None = None) -> Workspace | None:
        folder = (cfg or get_config()).work_dir / run_id
        path = folder / INFO_FILE
        if not path.exists():
            return None
        return cls(WorkspaceInfo.model_validate_json(path.read_text()), folder)

    def _save_info(self) -> None:
        with self._lock:
            write_atomic(self.folder / INFO_FILE, self.info.model_dump_json(indent=1))

    # ---- blobs and manifests

    @staticmethod
    def _put_blob(folder: Path, data: bytes) -> str:
        sha = _sha(data)
        path = folder / "blobs" / sha[:2] / sha
        if not path.exists():
            write_atomic(path, data)
        return sha

    def _blob(self, sha: str) -> bytes:
        return (self.folder / "blobs" / sha[:2] / sha).read_bytes()

    @staticmethod
    def _put_manifest(folder: Path, manifest: dict[str, str]) -> str:
        body = json.dumps(dict(sorted(manifest.items())))
        version = _sha(body.encode())[:16]
        path = folder / "manifests" / f"{version}.json"
        if not path.exists():
            write_atomic(path, body)
        return version

    def manifest(self, version: str) -> dict[str, str]:
        path = self.folder / "manifests" / f"{version}.json"
        if not path.exists():
            raise KeyError(f"unknown code version {version}")
        return json.loads(path.read_text())

    # ---- reading

    def read(self, rel: str, version: str | None = None) -> str | None:
        """A file's text at `version` (the applied one by default), or None if it does not exist,
        is binary, too big, or is a secret file. Files outside the editable set are read from
        disk (they never change during a run)."""
        rel = safe_rel(self.roots, rel)
        if not self.roots.is_readable(rel):
            return None  # a secret, a noise folder, or outside the paths the user gave
        files = self.manifest(version or self.info.applied_version)
        if rel in files:
            return _text(self._blob(files[rel]))
        path = self.roots.root / rel
        if not path.is_file() or path.stat().st_size > READ_MAX_BYTES:
            return None
        return _text(path.read_bytes())

    def attachments_text(self, each: int = 4000, total: int = 12_000) -> dict[str, str]:
        """Texts the command may be quoted from: explicitly listed files, plus README* files at
        the top of each given folder. Capped per file and in total."""
        names = list(self.info.editable_files)
        for d in self.info.editable_dirs:
            base = self.roots.root / d
            names += [(Path(d) / p.name).as_posix() for p in sorted(base.glob("README*"))
                      if p.is_file()]
        out: dict[str, str] = {}
        budget = total
        for rel in dict.fromkeys(names):
            if budget <= 0:
                break
            text = self.read(rel)
            if text:
                out[rel] = text[: min(each, budget)]
                budget -= len(out[rel])
        return out

    # ---- versions

    def commit_edit(self, base_version: str, edit: Edit) -> tuple[str, DiffStats]:
        """The version made by applying `edit` on `base_version`, and its diff size. Nothing on
        disk changes. EditError (one message per problem) if the edit does not apply."""
        with self._lock:
            return self._commit_edit(base_version, edit)

    def _commit_edit(self, base_version: str, edit: Edit) -> tuple[str, DiffStats]:
        problems: list[str] = []
        clean = edit.model_copy(deep=True)
        for e in [*clean.edits, *clean.new_files]:
            try:
                e.path = safe_rel(self.roots, e.path)
            except PathError as err:
                problems.append(f"{e.path}: {err}")
        if problems:
            raise EditError(problems)
        base = self.manifest(base_version)

        def read(rel: str) -> str | None:
            if rel in base:
                return _text(self._blob(base[rel]))
            return None  # a file outside the version is not editable or does not exist

        changed = apply_edit({}, clean, editable=self.roots.is_editable, read=read)
        for rel in changed:
            if rel in base:
                continue
            problem = self._in_the_way(rel)
            if problem:
                problems.append(f"new file {rel}: {problem}")
        if problems:
            raise EditError(problems)
        too_big = [rel for rel, text in changed.items() if len(text.encode()) > MAX_FILE_BYTES]
        if too_big:
            raise EditError([f"{rel}: the result is larger than {MAX_FILE_BYTES} bytes"
                             for rel in too_big])
        before = {rel: read(rel) for rel in changed}
        manifest = dict(base)
        for rel, text in changed.items():
            manifest[rel] = self._put_blob(self.folder, text.encode())
        return self._put_manifest(self.folder, manifest), diff_stats(before, changed)

    def _in_the_way(self, rel: str) -> str:
        """Why a new file may not be created at `rel` ("" if it may): something already exists
        there (or under another spelling of the name), or a parent is not a folder."""
        path = self.roots.root / rel
        if os.path.lexists(path):
            return ("something already exists at that path (or a name differing only in case); "
                    "edit the existing file instead")
        for parent in PurePosixPath(rel).parents:
            if str(parent) in ("", "."):
                continue
            full = self.roots.root / parent
            if os.path.lexists(full) and not full.is_dir():
                return f"{parent} is a file, not a folder"
        return ""

    def _disk_sha(self, rel: str) -> str | None:
        """The hash of the file on disk now (None if there is no regular file there), reusing
        the last hash while its size and mtime are unchanged."""
        path = self.roots.root / rel
        try:
            st = path.lstat()
        except FileNotFoundError:
            return None
        if not path.is_file() or path.is_symlink():
            return None
        cached = self._stats.get(rel)
        if cached and cached[:2] == (st.st_size, st.st_mtime_ns):
            return cached[2]
        sha = _sha(path.read_bytes())
        self._stats[rel] = (st.st_size, st.st_mtime_ns, sha)
        return sha

    def _owned(self, rel: str) -> bool:
        """Is `rel` one of the run's files: backed up at the start, or created by one of its
        versions? Only those may be overwritten or removed."""
        return rel in self.info.files or rel in self.manifest(self.info.applied_version)

    def apply_version(self, version: str) -> list[str]:
        """Write `version` to the user's files, compared with what is on disk now. Files that
        already match are left alone; a file the run created and `version` lacks is removed,
        unless someone changed it since (then it stays). WorkspaceConflict, before anything is
        written, if a file the run does not own is in the way. Returns the paths touched."""
        with self._lock:
            target = self.manifest(version)
            current = self.manifest(self.info.applied_version)
            for rel in target:
                if not self._owned(rel) and os.path.lexists(self.roots.root / rel):
                    raise WorkspaceConflict(f"{rel} exists on disk but is not one of the run's "
                                            f"files; it was not overwritten")
                if (self.roots.root / rel).is_dir():
                    raise WorkspaceConflict(f"{rel} is a folder on disk; it was not replaced")
            touched = []
            for rel, sha in target.items():
                if self._disk_sha(rel) == sha:
                    continue
                path = self.roots.root / rel
                mode = path.stat().st_mode if path.exists() else None
                path.parent.mkdir(parents=True, exist_ok=True)
                write_atomic(path, self._blob(sha))
                if mode is not None:
                    os.chmod(path, mode)
                self._stats.pop(rel, None)
                touched.append(rel)
            for rel in current.keys() - target.keys():
                if self._disk_sha(rel) == current[rel]:  # ours, unchanged: remove it
                    (self.roots.root / rel).unlink()
                    self._stats.pop(rel, None)
                    touched.append(rel)
            for rel in touched:
                if rel.endswith(".py"):
                    self._drop_bytecode(self.roots.root / rel)
            self.info.applied_version = version
            self._save_info()
            return sorted(touched)

    @staticmethod
    def _drop_bytecode(source: Path) -> None:
        """Remove the cached bytecode of a Python file that was just rewritten. Python checks a
        .pyc against the source's size and whole-second mtime, so a same-size rewrite within the
        same second (common when versions swap between experiments) would run stale code."""
        cache = source.parent / "__pycache__"
        if cache.is_dir():
            for pyc in cache.glob(f"{source.stem}.*.pyc"):
                pyc.unlink(missing_ok=True)

    def restore_baseline(self) -> list[str]:
        return self.apply_version(self.info.baseline_version)

    def patch(self, version: str | None = None) -> str:
        """Unified diff from the baseline to `version` (the applied one by default)."""
        return self.diff(self.info.baseline_version, version or self.info.applied_version)

    def diff(self, from_version: str, to_version: str) -> str:
        """Unified diff between two versions."""
        base = self.manifest(from_version)
        target = self.manifest(to_version)
        chunks = []
        for rel in sorted(base.keys() | target.keys()):
            if base.get(rel) == target.get(rel):
                continue
            old = _text(self._blob(base[rel])) if rel in base else ""
            new = _text(self._blob(target[rel])) if rel in target else ""
            if old is None or new is None:
                chunks.append(f"Binary file {rel} differs\n")
                continue
            chunks += unified_diff(old, new, fromfile=f"a/{rel}" if rel in base else "/dev/null",
                                   tofile=f"b/{rel}" if rel in target else "/dev/null")
        return "".join(chunks)
