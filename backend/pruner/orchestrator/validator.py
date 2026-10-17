"""Checks on a proposed edit before it becomes a node (no LLM, nothing written to the user's files).

check_edit() builds the edit's code version in memory and refuses it, with one plain message per
problem (fed back to the agent for its one repair attempt), when:
  - it is empty, or has too many edits / files (cfg.max_edits, cfg.max_edit_files);
  - it repeats an earlier proposal of the run (same normalized edits);
  - it does not apply: a path outside the run's files or not editable, `find` not found or
    ambiguous, a new file that already exists (see workspace/edits.py);
  - a changed file no longer parses (.py, .json, .toml; other types are not checked, noted);
  - it removes or changes an existing signature: a Python function's or class's arguments (new
    ones may be added), or a top-level key of a JSON/TOML file;
  - the diff is larger than cfg.max_diff_lines (added + removed lines);
  - the experiment command would no longer find the scripts it names.
"""

from __future__ import annotations

import ast
import hashlib
import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field

from pruner.core.config import Config
from pruner.core.models import DiffStats, Edit, RunCommand
from pruner.runs.command import SCRIPT_SUFFIXES
from pruner.workspace.edits import EditError
from pruner.workspace.paths import PathError
from pruner.workspace.workspace import Workspace


class ProposalRejected(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Checked:
    version: str
    stats: DiffStats
    notes: list[str] = field(default_factory=list)  # e.g. file types that were not syntax-checked


def fingerprint(edit: Edit) -> str:
    """The same edit, whatever its whitespace or order."""
    def norm(text: str) -> str:
        return " ".join(text.split())

    parts = sorted([("e", e.path, norm(e.find), norm(e.replace)) for e in edit.edits]
                   + [("n", n.path, "", norm(n.content)) for n in edit.new_files])
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:16]


# ---- syntax and signatures


def _syntax_problem(rel: str, text: str) -> str | None | bool:
    """A problem message, None if it parses, or False if this file type is not checked."""
    try:
        if rel.endswith(".py"):
            ast.parse(text)
        elif rel.endswith(".json"):
            json.loads(text)
        elif rel.endswith(".toml"):
            tomllib.loads(text)
        else:
            return False
    except SyntaxError as e:
        return f"{rel} no longer parses: {e.msg} (line {e.lineno})"
    except (ValueError, tomllib.TOMLDecodeError) as e:
        return f"{rel} is no longer valid: {e}"
    return None


def _py_signatures(text: str) -> dict[str, str]:
    """qualname -> argument list of top-level functions and classes, and of class methods."""
    out: dict[str, str] = {}

    def args_of(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        a = fn.args
        names = [p.arg for p in [*a.posonlyargs, *a.args]]
        if a.vararg:
            names.append("*" + a.vararg.arg)
        names += [p.arg for p in a.kwonlyargs]
        if a.kwarg:
            names.append("**" + a.kwarg.arg)
        return ", ".join(names)

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = args_of(node)
        elif isinstance(node, ast.ClassDef):
            out[node.name] = "class"
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{item.name}"] = args_of(item)
    return out


def _kept_args(old: str, new: str) -> bool:
    """New may add arguments after the old ones (with defaults or *args), not drop or rename."""
    old_names = [n for n in old.split(", ") if n]
    new_names = [n for n in new.split(", ") if n]
    return new_names[: len(old_names)] == old_names


def _signature_problems(rel: str, before: str, after: str) -> list[str]:
    problems = []
    if rel.endswith(".py"):
        old, new = _py_signatures(before), _py_signatures(after)
        for name, args in old.items():
            if name not in new:
                problems.append(f"{rel}: {name} was removed; keep existing functions and "
                                f"classes (add new ones instead)")
            elif args != "class" and not _kept_args(args, new[name]):
                problems.append(f"{rel}: the signature of {name}({args}) changed to "
                                f"({new[name]}); keep its arguments (new ones may be added)")
    elif rel.endswith((".json", ".toml")):
        try:
            load = json.loads if rel.endswith(".json") else tomllib.loads
            old_keys, new_keys = load(before), load(after)
        except (ValueError, tomllib.TOMLDecodeError):
            return problems
        if isinstance(old_keys, dict) and isinstance(new_keys, dict):
            gone = sorted(old_keys.keys() - new_keys.keys())
            if gone:
                problems.append(f"{rel}: top-level keys removed: {', '.join(gone)}")
    return problems


# ---- the check


def check_edit(ws: Workspace, base_version: str, edit: Edit, *, cfg: Config,
               seen: Mapping[str, str] | None = None,
               command: RunCommand | None = None) -> Checked:
    """The edit's version and diff size, or ProposalRejected with every problem found. `seen`
    maps fingerprints of the run's earlier proposals to their node ids."""
    count = len(edit.edits) + len(edit.new_files)
    if count == 0:
        raise ProposalRejected(["the hypothesis has no edit; every hypothesis must change code"])
    problems = []
    if count > cfg.max_edits:
        problems.append(f"{count} edits; at most {cfg.max_edits} per hypothesis")
    files = {e.path for e in edit.edits} | {n.path for n in edit.new_files}
    if len(files) > cfg.max_edit_files:
        problems.append(f"it touches {len(files)} files; at most {cfg.max_edit_files}")
    fp = fingerprint(edit)
    if seen and fp in seen:
        problems.append(f"it repeats the edit of {seen[fp]}; propose something different")
    if problems:
        raise ProposalRejected(problems)
    try:
        version, stats = ws.commit_edit(base_version, edit)
    except EditError as e:
        raise ProposalRejected(e.problems) from None

    notes: list[str] = []
    changed = sorted(set(ws.manifest(version).items()) - set(ws.manifest(base_version).items()))
    for rel, _ in changed:
        after = ws.read(rel, version) or ""
        syntax = _syntax_problem(rel, after)
        if syntax is False:
            notes.append(f"{rel}: not syntax-checked (unknown file type)")
        elif syntax:
            problems.append(syntax)
            continue
        before = ws.read(rel, base_version)
        if before is not None:
            problems += _signature_problems(rel, before, after)
    if stats.added + stats.removed > cfg.max_diff_lines:
        problems.append(f"the diff changes {stats.added + stats.removed} lines; at most "
                        f"{cfg.max_diff_lines} (make one focused change)")
    if command is not None:
        for token in command.text.split():
            if not token.endswith(SCRIPT_SUFFIXES) or token.startswith("-"):
                continue
            try:
                gone = ws.read(token, version) is None
            except PathError:
                continue  # a script outside the run's files: the edit cannot have touched it
            if gone and not (ws.roots.root / token).exists():
                problems.append(f"the experiment command needs {token}, which would no "
                                f"longer exist")
    if problems:
        raise ProposalRejected(problems)
    return Checked(version, stats, notes)
