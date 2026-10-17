"""The user's files for one run, edited in place, with versions and a baseline backup.

There is no copy and no sandbox: experiments change the real files. What this module adds is the
bookkeeping that makes that safe to undo:

- At the start every editable file is backed up once to <work_dir>/<run_id>/baseline/.
- A code version is a manifest (path -> content hash) over content-addressed blobs, all under
  <work_dir>/<run_id>/. commit_edit() makes a new version from a base version and an Edit in
  memory, so a proposed (or parked) node already has a version without touching the disk.
- apply_version() writes a version to the real files, changing only files that differ from the
  version currently applied (and removing files that only the old version created).
- patch() is the unified diff from the baseline to a version, for the user to keep or reverse.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
from pathlib import Path

from pruner.core.config import Config, get_config
from pruner.core.fs import write_atomic
from pruner.core.models import DiffStats, Edit, WorkspaceInfo
from pruner.workspace.edits import EditError, apply_edit, diff_stats
from pruner.workspace.paths import (
    MAX_FILE_BYTES,
    PathError,
    Roots,
    is_secret,
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


class Workspace:
    def __init__(self, info: WorkspaceInfo, folder: Path) -> None:
        self.info = info
        self.folder = folder  # <work_dir>/<run_id>
        self.roots = Roots(root=Path(info.root), editable_dirs=tuple(info.editable_dirs),
                           editable_files=tuple(info.editable_files))

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
        write_atomic(self.folder / INFO_FILE, self.info.model_dump_json(indent=1))

    # ---- blobs and manifests

    @staticmethod
    def _put_blob(folder: Path, data: bytes) -> str:
        sha = _sha(data)
        path = folder / "blobs" / sha[:2] / sha
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
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
        if is_secret(rel):
            return None
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
        too_big = [rel for rel, text in changed.items() if len(text.encode()) > MAX_FILE_BYTES]
        if too_big:
            raise EditError([f"{rel}: the result is larger than {MAX_FILE_BYTES} bytes"
                             for rel in too_big])
        before = {rel: read(rel) for rel in changed}
        manifest = dict(base)
        for rel, text in changed.items():
            manifest[rel] = self._put_blob(self.folder, text.encode())
        return self._put_manifest(self.folder, manifest), diff_stats(before, changed)

    def apply_version(self, version: str) -> list[str]:
        """Write `version` to the user's files. Only files that differ from the applied version
        are written; files the old version created and the new one lacks are removed. Returns the
        paths touched."""
        target = self.manifest(version)
        current = self.manifest(self.info.applied_version)
        touched = []
        for rel, sha in target.items():
            if current.get(rel) == sha:
                continue
            path = self.roots.root / rel
            mode = path.stat().st_mode if path.exists() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.pruner-tmp")
            tmp.write_bytes(self._blob(sha))
            if mode is not None:
                os.chmod(tmp, mode)
            tmp.replace(path)
            touched.append(rel)
        for rel in current.keys() - target.keys():
            path = self.roots.root / rel
            if path.exists():
                path.unlink()
            touched.append(rel)
        self.info.applied_version = version
        self._save_info()
        return sorted(touched)

    def restore_baseline(self) -> list[str]:
        return self.apply_version(self.info.baseline_version)

    def patch(self, version: str | None = None) -> str:
        """Unified diff from the baseline to `version` (the applied one by default)."""
        base = self.manifest(self.info.baseline_version)
        target = self.manifest(version or self.info.applied_version)
        chunks = []
        for rel in sorted(base.keys() | target.keys()):
            if base.get(rel) == target.get(rel):
                continue
            old = _text(self._blob(base[rel])) if rel in base else ""
            new = _text(self._blob(target[rel])) if rel in target else ""
            if old is None or new is None:
                chunks.append(f"Binary file {rel} differs\n")
                continue
            chunks += difflib.unified_diff(
                old.splitlines(keepends=True), new.splitlines(keepends=True),
                fromfile=f"a/{rel}" if rel in base else "/dev/null",
                tofile=f"b/{rel}" if rel in target else "/dev/null")
        return "".join(chunks)
