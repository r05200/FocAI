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
from pruner.core.models import DeadEnd, Finding, Node, Run, RunIdea
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
    ideas: Sequence[RunIdea] = ()  # the run vault: this run's ideas and whole-branch findings


METRICS_SHOWN = 6
OTHER_BRANCHES_SHOWN = 12


def measured(node: Node | None) -> bool:
    return node is not None and node.experiment is not None and not node.experiment.error


def best_node(nodes: Sequence[Node]) -> Node | None:
    """The supported, measured node with the best judge score (then confidence), if any."""
    good = [n for n in nodes if n.verdict == "supported" and n.status == "done" and measured(n)]
    return max(good, key=lambda n: (n.post_score or 0.0,
                                    n.synthesis.confidence if n.synthesis else 0.0),
               default=None)


def previous_measured(nodes: Sequence[Node], node: Node) -> Node | None:
    """The nearest measured node above `node` on its path (the previous round)."""
    for n in reversed(ancestors(nodes, node)[:-1]):
        if measured(n):
            return n
    return None


def compare_metrics(current: dict[str, float], previous: dict[str, float] | None,
                    against: str = "", limit: int = METRICS_SHOWN) -> str:
    """"ms=6 (-25% vs n2), mem.mb=3 (same)": the values and how each moved since `against`."""
    parts = []
    for key, value in list(current.items())[:limit]:
        text = f"{key}={value:g}"
        old = (previous or {}).get(key)
        if old is not None:
            if old == value:
                text += " (same)"
            elif old != 0:
                text += f" ({(value - old) / abs(old):+.0%} vs {against or 'before'})"
            else:
                text += f" (was {old:g})"
        parts.append(text)
    return ", ".join(parts)


def trend_text(nodes: Sequence[Node], node: Node) -> str:
    """The measured values along the path to `node`, each compared with the round before it, so
    the agent can tell whether the last step went the right way."""
    lines, before = [], None
    for n in ancestors(nodes, node):
        if not measured(n):
            continue
        assert n.experiment is not None
        name = "baseline" if n.parent_id is None else f"[{n.family or '-'}] {n.description}"
        lines.append(f"- {n.id} {name}: " + (compare_metrics(
            n.experiment.metrics, before.experiment.metrics if before and before.experiment
            else None, before.id if before else "") or "(no numbers)"))
        before = n
    return "\n".join(lines) or "(nothing measured on this path yet)"


def best_text(nodes: Sequence[Node]) -> str:
    best = best_node(nodes)
    if best is None or best.experiment is None:
        return "(no supported result yet)"
    root = next((n for n in nodes if n.parent_id is None), None)
    base = root.experiment.metrics if measured(root) and root and root.experiment else None
    return (f"{best.id} [{best.family or '-'}] {best.description}: "
            + (compare_metrics(best.experiment.metrics, base, "baseline") or best.result or ""))


def other_branches_text(nodes: Sequence[Node], node: Node,
                        limit: int = OTHER_BRANCHES_SHOWN) -> str:
    """Measured nodes off this node's path: what other branches tried and what it gave, so a
    knob-turning search can see which settings moved the result which way."""
    on_path = {n.id for n in ancestors(nodes, node)}
    root = next((n for n in nodes if n.parent_id is None), None)
    base = root.experiment.metrics if measured(root) and root and root.experiment else None
    rows = [n for n in nodes if n.id not in on_path and measured(n) and n.type != "conclusion"]
    lines = []
    for n in rows[-limit:]:
        assert n.experiment is not None
        lines.append(f"- {n.id} [{n.family or '-'}] {n.verdict or n.status}: {n.description} | "
                     + (compare_metrics(n.experiment.metrics, base, "baseline")
                        or n.result or ""))
    more = len(rows) - len(lines)
    return "\n".join(lines + ([f"({more} older ones not shown: use get_results)"] if more > 0
                                else [])) or "(no other branch has a result yet)"


RUN_VAULT_SHOWN = 10


def run_vault_text(ideas: Sequence[RunIdea], limit: int = RUN_VAULT_SHOWN) -> str:
    """The run vault for a prompt: whole-branch findings first (the agent was fairly sure), then
    the latest ideas. The prompt says to use it only where it helps."""
    branch = [i for i in ideas if i.kind == "branch_finding"]
    rest = [i for i in ideas if i.kind != "branch_finding"]
    shown = (branch[-limit:] + rest[-max(0, limit - len(branch[-limit:])):])[:limit]
    lines = []
    for i in shown:
        sure = f", {i.confidence:.0%} sure" if i.confidence is not None else ""
        kind = "branch finding" if i.kind == "branch_finding" else "idea"
        lines.append(f"- [{kind}{sure}] {i.title}: {i.summary} ({i.branch})")
    return "\n".join(lines) or "(the run vault is empty)"


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
        "run_vault": run_vault_text(view.ideas),
        "trend": trend_text(view.nodes, node),
        "best": best_text(view.nodes),
        "other_branches": other_branches_text(view.nodes, node),
        "budget": (f"{max(0, run.caps.node_budget - experiments)} experiment(s) left of "
                   f"{run.caps.node_budget}; this node is at depth {node.depth} of at most "
                   f"{run.caps.max_depth}; families tried so far: "
                   f"{', '.join(families) or 'none'}"),
    }
