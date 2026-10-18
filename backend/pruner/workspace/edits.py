"""Applying an Edit (search/replace) to file texts in memory.

Nothing here touches the disk. apply_edit() returns the new texts of the files it changed, or
raises EditError with one message per problem, worded so the agent can fix its edit.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Mapping

from pruner.core.models import DiffStats, Edit


class EditError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _lines_of(text: str, needle: str) -> list[int]:
    """The line numbers (1-based) where `needle` starts in `text`."""
    lines, start = [], 0
    while (i := text.find(needle, start)) != -1:
        lines.append(text.count("\n", 0, i) + 1)
        start = i + 1
    return lines


def apply_edit(files: Mapping[str, str], edit: Edit, *, editable: Callable[[str], bool],
               read: Callable[[str], str | None]) -> dict[str, str]:
    """New texts of the files `edit` changes. `files` holds texts already known (the base version);
    `read(rel)` loads any other file; `editable(rel)` says whether it may change."""
    problems: list[str] = []
    out: dict[str, str] = {}

    def current(rel: str) -> str | None:
        if rel in out:
            return out[rel]
        return files[rel] if rel in files else read(rel)

    for i, e in enumerate(edit.edits, 1):
        if not editable(e.path):
            problems.append(f"edit {i}: {e.path} may not be changed")
            continue
        text = current(e.path)
        if text is None:
            problems.append(f"edit {i}: {e.path} does not exist")
            continue
        if not e.find:
            problems.append(f"edit {i}: `find` is empty")
            continue
        where = _lines_of(text, e.find)
        if not where:
            problems.append(f"edit {i}: the `find` text was not found in {e.path}")
            continue
        if len(where) > 1 and not e.replace_all:
            problems.append(f"edit {i}: the `find` text is ambiguous in {e.path}: {len(where)} "
                            f"matches at lines {', '.join(map(str, where[:6]))}; include more "
                            f"surrounding text")
            continue
        new = text.replace(e.find, e.replace) if e.replace_all else text.replace(e.find,
                                                                                 e.replace, 1)
        if new == text:
            problems.append(f"edit {i}: it changes nothing in {e.path}")
            continue
        out[e.path] = new
    for n in edit.new_files:
        if not editable(n.path):
            problems.append(f"new file {n.path}: that path may not be created")
        elif current(n.path) is not None:
            problems.append(f"new file {n.path}: it already exists; edit it instead")
        else:
            out[n.path] = n.content
    if problems:
        raise EditError(problems)
    if not out:
        raise EditError(["the edit changes nothing"])
    return out


def unified_diff(old: str, new: str, fromfile: str, tofile: str) -> list[str]:
    """difflib's unified diff, made safe to apply: a last line with no newline gets one plus
    git's "\\ No newline at end of file" marker, instead of running into the next line."""
    out = []
    for line in difflib.unified_diff(old.splitlines(keepends=True),
                                     new.splitlines(keepends=True), fromfile=fromfile,
                                     tofile=tofile):
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return out


def diff_stats(before: Mapping[str, str | None], after: Mapping[str, str]) -> DiffStats:
    added = removed = 0
    for rel, new in after.items():
        old = before.get(rel) or ""
        for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
    return DiffStats(files=len(after), added=added, removed=removed)
