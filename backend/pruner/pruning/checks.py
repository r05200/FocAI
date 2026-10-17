"""Deterministic checks on a proposed experiment, run before any LLM judging (no tokens spent).

A proposal is rejected if its new train.py does not compile, it touches a file other than
train.py, build_model / build_optimizer change their signatures, or the diff is large.
"""

from __future__ import annotations

import ast
import difflib
from collections.abc import Iterable

from pruner.core.models import Decision, Node

PROTECTED_SIGNATURES = ("build_model", "build_optimizer")
MAX_CHANGED_LINES = 60  # added plus removed lines


def _signatures(tree: ast.Module) -> dict[str, list[str]]:
    return {
        n.name: [a.arg for a in (*n.args.posonlyargs, *n.args.args, *n.args.kwonlyargs)]
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in PROTECTED_SIGNATURES
    }


def check_train_py(new_source: str, baseline_source: str, *,
                   changed_files: Iterable[str] = ("train.py",),
                   max_changed_lines: int = MAX_CHANGED_LINES) -> list[str]:
    """Return the violations found; an empty list means the proposal may go on to the judge."""
    violations = [f"changes {f}, only train.py may change"
                  for f in changed_files if f != "train.py"]
    try:
        new_tree = ast.parse(new_source)
    except SyntaxError as e:
        return [*violations, f"train.py does not compile: {e.msg} (line {e.lineno})"]

    baseline = _signatures(ast.parse(baseline_source))
    new = _signatures(new_tree)
    for name, args in baseline.items():
        if name not in new:
            violations.append(f"{name} was removed")
        elif new[name] != args:
            violations.append(f"{name} signature changed from ({', '.join(args)}) "
                              f"to ({', '.join(new[name])})")

    diff = difflib.unified_diff(baseline_source.splitlines(), new_source.splitlines(), lineterm="")
    changed = sum(1 for line in diff
                  if line[:1] in "+-" and not line.startswith(("+++", "---")))
    if changed > max_changed_lines:
        violations.append(f"diff changes {changed} lines (limit {max_changed_lines})")
    return violations


def reject(node: Node, violations: list[str]) -> Node:
    """Record a failed check on the node, the same way a low pre-score would."""
    node.decision = Decision(verdict="park", stage="pre",
                             reason="Rejected before scoring: " + "; ".join(violations))
    node.decided_by = "agent"
    node.status = "parked"
    return node
