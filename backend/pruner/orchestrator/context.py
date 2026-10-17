"""The compact state every agent prompt is rebuilt from (nothing is carried over between calls).

build_context() is a pure function of what is stored: the node's code version, one-line
summaries of its ancestors, the shared findings log, the instructions and directives, the
objectives, the command, the budget left, dead ends, and the node's existing children.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pruner.core import prompts
from pruner.core.config import Config
from pruner.core.models import DeadEnd, Finding, Node, Run
from pruner.workspace.paths import is_secret
from pruner.workspace.workspace import Workspace

FINDINGS_SHOWN = 15


@dataclass
class RunView:
    """What a phase may read about the run."""

    run: Run
    nodes: Sequence[Node]
    findings: Sequence[Finding]
    dead_ends: Sequence[DeadEnd]
    workspace: Workspace | None


def node_line(node: Node) -> str:
    """One line about a node, for ancestor and sibling lists."""
    family = f"[{node.family}] " if node.family else ""
    text = node.summary or (node.hypothesis.statement if node.hypothesis else node.description)
    verdict = f" {node.verdict}" if node.verdict else ""
    return f"{node.id} {family}{node.status}{verdict}: {text}"


def ancestors(nodes: Sequence[Node], node: Node) -> list[Node]:
    """Root first, ending with `node` itself."""
    by_id = {n.id: n for n in nodes}
    path, current = [], node
    while current is not None:
        path.append(current)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return list(reversed(path))


def render_code(ws: Workspace | None, version: str | None, budget: int) -> str:
    """The editable files at `version`: a listing, then their text while it fits in `budget`
    characters (smaller files first), then the changes made so far against the baseline."""
    if ws is None:
        return "(this run has no files)"
    version = version or ws.info.applied_version
    files = [f for f in ws.info.files if not is_secret(f)]
    texts = {f: ws.read(f, version) for f in files}
    listing = "\n".join(f"- {f} ({len(t)} chars)" if t is not None else f"- {f} (binary)"
                        for f, t in texts.items())
    parts = [f"Files you may edit (root {ws.info.root}):\n{listing or '(none)'}"]
    left = budget
    shown = []
    for f, t in sorted(((f, t) for f, t in texts.items() if t), key=lambda x: len(x[1])):
        if len(t) > left:
            continue
        shown.append(f"=== {f}\n{t}")
        left -= len(t)
    hidden = len([t for t in texts.values() if t]) - len(shown)
    if shown:
        parts.append("\n\n".join(shown))
    if hidden:
        parts.append(f"({hidden} more file(s) not shown: use read_file)")
    diff = ws.patch(version)
    if diff:
        parts.append("Changes so far against the original files:\n" + diff[: budget // 4])
    return "\n\n".join(parts)


def build_context(view: RunView, node: Node, cfg: Config) -> dict[str, str]:
    run = view.run
    path = ancestors(view.nodes, node)
    children = [n for n in view.nodes if n.parent_id == node.id]
    experiments = sum(1 for n in view.nodes if n.experiment is not None)
    families = sorted({n.family for n in view.nodes if n.family})
    findings = list(view.findings)[-FINDINGS_SHOWN:]
    return {
        "question": run.question,
        "instructions": prompts.render_instructions(run.instructions, run.directives),
        "objectives": prompts.render_objectives(run.objectives),
        "command": run.command.text if run.command else "(none yet)",
        "code": render_code(view.workspace, node.version, cfg.code_context_chars),
        "ancestors": "\n".join(node_line(n) for n in path) or "(this is the start)",
        "findings": "\n".join(f"- {f.node_id or '-'} [{f.verdict}] {f.text}" for f in findings)
        or "(none yet)",
        "siblings": "\n".join(node_line(n) for n in children) or "(none yet)",
        "dead_ends": prompts.render_dead_ends(view.dead_ends),
        "budget": (f"{max(0, run.caps.node_budget - experiments)} experiment(s) left of "
                   f"{run.caps.node_budget}; this node is at depth {node.depth} of at most "
                   f"{run.caps.max_depth}; families tried so far: "
                   f"{', '.join(families) or 'none'}"),
    }
