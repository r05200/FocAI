"""The hypothesis phase: the agent proposes the next experiments from a node.

expand(parent) does, in order:
  1. One agent call (the hypothesis model, with its read tools and the findings-log tool; every
     tool call is logged on `parent` with its reason) for up to `count` hypotheses from different
     families, each with a planned experiment and a search/replace edit.
  2. Validation of every edit in memory (orchestrator/validator.py). The proposals that fail get
     ONE batched repair call with the exact problems; whatever still fails is dropped (logged).
  3. One proposal per family is kept, up to `count`.
  4. Each survivor becomes a child node with its own code version (nothing is written to the
     user's files) and a deterministic id (n2, n3, ...).
  A run without files is a research run: the agent guesses what the user wants to see, and each
  hypothesis carries 1-3 search queries instead of an edit (propose_research.md). They are only
  checked for having queries and not repeating earlier searches (no repair call, no version).
  5. The pre-score judge ranks the siblings together (PreScorer.score_siblings). The low zone is
     parked (kept, restorable, recorded as a dead end); a near-duplicate of earlier work is parked
     too. pre_band shows the zone as low / medium / high.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from pruner.agent.toolloop import AgentSession
from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.events import Activity, NodeCreated, NodeUpdated
from pruner.core.llm import LLM
from pruner.core.models import (
    DeadEnd,
    Decision,
    Edit,
    FileEdit,
    HypothesisSpec,
    LogEntry,
    NewFile,
    Node,
    PreBand,
)
from pruner.orchestrator.context import RunView, build_context, render_code
from pruner.orchestrator.validator import ProposalRejected, check_edit, fingerprint
from pruner.pruning import prescorer as pre
from pruner.pruning.prescorer import PreScorer
from pruner.pruning.scale import to_ten

if TYPE_CHECKING:
    from pruner.runs.manager import LiveRun, RunManager

MAX_PER_EXPANSION = 3
BANDS: dict[str, PreBand] = {"park": "low", "borderline": "medium", "run": "high"}
MODE_BRIEFS = {
    "initial": "These are the first experiments, starting from the original files.",
    "more_experiments": "Refine or vary this node's hypothesis (same family): a cleaner or "
                        "stronger version of the change, or a check that the result holds.",
    "new_hypothesis": "Try a different family than the ones already tried from here.",
    "diagnose": "The last result was surprising or the run failed: propose experiments that "
                "explain why (for example undo one part, or add measurement to the output).",
    "combine": "Combine the supported changes named below into one experiment.",
    "resolve": "A result contradicts a note or an earlier finding: design an experiment that "
               "tells the two apart.",
    "transfer": "Apply the supported change named below to another part of the code.",
}
# A research run (no files): a hypothesis is a guess about what the user wants to see, and its
# experiment searches for resources that would show it (orchestrator/research.py).
RESEARCH_BRIEFS = {
    "initial": "These are the first searches: guess what the user most wants to see.",
    "more_experiments": "Dig deeper in this node's direction (same family): narrower or "
                        "follow-up searches, or a check that what was found holds up.",
    "new_hypothesis": "Make a different guess (another family) than the ones tried from here.",
    "diagnose": "The last search found nothing useful, or something surprising: search in a way "
                "that explains why (other wording, other kinds of sources).",
    "combine": "Combine the supported directions named below into one search.",
    "resolve": "A resource contradicts a note or an earlier finding: search for what tells the "
               "two apart.",
    "transfer": "Look for the same kind of resource for another part of the question.",
}


def short_title(text: str, limit: int = 90) -> str:
    """The first sentence of `text`, cut to `limit` characters (when the model gave no title)."""
    first = " ".join(text.split()).split(". ")[0].rstrip(".")
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


class ProposedHypothesis(BaseModel):
    family: str
    title: str = ""  # at most 12 words: the node's label in the UI
    statement: str
    rationale: str = ""
    planned_experiment: str = ""
    expected_signal: str = ""
    measures: list[str] = Field(default_factory=list)
    edits: list[FileEdit] = Field(default_factory=list)
    new_files: list[NewFile] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)  # research runs: the searches to run
    vault_items_used: list[str] = Field(default_factory=list)


class ProposeOutput(BaseModel):
    hypotheses: list[ProposedHypothesis] = Field(default_factory=list)


def family_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "general"


def next_node_ids(nodes: list[Node], count: int) -> list[str]:
    """Deterministic ids n<k> after the highest one used (so prompts and caches are stable)."""
    used = [int(m.group(1)) for n in nodes if (m := re.fullmatch(r"n(\d+)", n.id))]
    start = max(used, default=0) + 1
    return [f"n{start + i}" for i in range(count)]


def query_key(queries: list[str]) -> str:
    return "|".join(sorted(" ".join(q.lower().split()) for q in queries))


def code_base(parent: Node) -> str | None:
    """The code a child builds on: the parent's own version if it was supported (or is the
    baseline), else the code the parent started from, so refuted changes are not stacked."""
    if parent.parent_id is None or parent.verdict == "supported":
        return parent.version
    return parent.base_version or parent.version


class HypothesisPhase:
    def __init__(self, llm: LLM, prescorer: PreScorer, cfg: Config | None = None) -> None:
        self.llm = llm
        self.prescorer = prescorer
        self.cfg = cfg or get_config()

    def limits(self, state: LiveRun) -> str:
        if state.workspace is None:
            return (f"1 to {self.cfg.research_queries_max} short search queries per hypothesis "
                    f"(they search the user's vault and, if set up, the web); no file edits: "
                    f"this run has no files.")
        ws = state.workspace
        where = "no files"
        if ws is not None:
            scope = ["any file under the root" if d == "" else f"files under {d}/"
                     for d in ws.info.editable_dirs] + list(ws.info.editable_files)
            where = ", ".join(scope)
        return (f"at most {self.cfg.max_edits} edits in {self.cfg.max_edit_files} files and "
                f"{self.cfg.max_diff_lines} changed lines; editable: {where}; keep existing "
                f"function signatures and config keys; add no new dependencies.")

    def _validate(self, state: LiveRun, base: str, proposals: list[ProposedHypothesis],
                  seen: dict[str, str]):
        ok, failed = [], []
        for p in proposals:
            edit = Edit(edits=p.edits, new_files=p.new_files)
            try:
                checked = check_edit(state.workspace, base, edit, cfg=self.cfg,  # type: ignore[arg-type]
                                     seen=seen, command=state.run.command)
            except ProposalRejected as e:
                failed.append((p, e.problems))
                continue
            edit.stats = checked.stats
            seen[fingerprint(edit)] = "this batch"
            ok.append((p, edit, checked))
        return ok, failed

    async def expand(self, host: RunManager, state: LiveRun, parent: Node, *,
                     mode: str = "initial", brief: str = "", count: int | None = None
                     ) -> list[Node]:
        run = state.run
        live = [n for n in state.nodes if n.parent_id == parent.id
                and n.status not in ("parked", "failed")]
        room = max(0, run.caps.branching - len(live))
        count = min(count or MAX_PER_EXPANSION, MAX_PER_EXPANSION, room)
        if count == 0:
            host._log(state, parent.id, LogEntry(kind="decision", title="No new hypotheses",
                                                 text="The branching limit for this node is "
                                                      "reached."))
            return []
        research = state.workspace is None
        view = RunView(run=run, nodes=state.nodes, findings=state.findings,
                       dead_ends=state.dead_ends, workspace=state.workspace, ideas=state.ideas)
        values = build_context(view, parent, self.cfg)
        if research:
            del values["code"], values["command"]
        briefs = RESEARCH_BRIEFS if research else MODE_BRIEFS
        prompt = prompts.render(
            "propose_research" if research else "propose", count=count, mode=mode,
            mode_brief=(briefs.get(mode, "") + (f" {brief}" if brief else "")).strip(),
            limits=self.limits(state), **values)
        runner = host._runner(state, parent, "hypothesis")
        out = await AgentSession(self.llm, self.cfg).run(
            ProposeOutput, prompt, model=self.cfg.agent_hypothesis_model, purpose="propose",
            runner=runner)
        parent.tokens.agent += out.tokens.total
        if out.records:
            parent.tool_calls["hypothesis"] = parent.tool_calls.get("hypothesis", 0) + len(
                out.records)

        if research:
            base = None
            ok = self._check_research(host, state, parent, out.value.hypotheses)
        else:
            base = code_base(parent)
            assert base is not None
            seen = {fingerprint(n.edit): n.id for n in state.nodes if n.edit}
            ok, failed = self._validate(state, base, out.value.hypotheses, seen)
            if failed:
                ok += await self._repair(host, state, parent, base, failed, seen)

        kept, families = [], set()
        for p, edit, checked in ok:
            family = family_slug(p.family)
            if family in families:
                host._log(state, parent.id, LogEntry(
                    kind="decision", title=f"Dropped a second '{family}' hypothesis",
                    text=f"Siblings must come from different families: {p.statement}"))
                continue
            families.add(family)
            kept.append((p, edit, checked, family))
        kept = kept[:count]
        if not kept:
            host._emit(state, Activity, node_id=parent.id,
                       message="The agent proposed no hypothesis that could be applied.")
            return []
        return await self._create_and_score(host, state, parent, base, kept)

    def _check_research(self, host: RunManager, state: LiveRun, parent: Node,
                        proposals: list[ProposedHypothesis]) -> list:
        """A research hypothesis needs at least one query and must not repeat earlier searches
        (there is nothing to repair, so failures are just dropped and logged)."""
        seen = {query_key(n.hypothesis.queries) for n in state.nodes
                if n.hypothesis and n.hypothesis.queries}
        ok = []
        for p in proposals:
            queries = [q.strip()[:200] for q in p.queries if q.strip()]
            queries = queries[: self.cfg.research_queries_max]
            problem = ("it has no search queries" if not queries
                       else "it repeats earlier searches" if query_key(queries) in seen else "")
            if problem:
                host._log(state, parent.id, LogEntry(
                    kind="error", title=f"Dropped a '{family_slug(p.family)}' hypothesis",
                    text=f"{p.statement}\nWhy: {problem}."))
                continue
            seen.add(query_key(queries))
            p.queries = queries
            ok.append((p, None, None))
        return ok

    async def _repair(self, host: RunManager, state: LiveRun, parent: Node, base: str,
                      failed: list, seen: dict[str, str]) -> list:
        failures = json.dumps([{"hypothesis": p.model_dump(), "problems": problems}
                               for p, problems in failed], indent=1)
        prompt = prompts.render(
            "propose_repair", failures=failures, limits=self.limits(state),
            code=render_code(state.workspace, base, self.cfg.code_context_chars))
        out = await AgentSession(self.llm, self.cfg).run(
            ProposeOutput, prompt, model=self.cfg.agent_hypothesis_model, purpose="propose")
        parent.tokens.agent += out.tokens.total
        ok, still = self._validate(state, base, out.value.hypotheses, seen)
        repaired = {family_slug(p.family) for p, _, _ in ok}
        for p, problems in failed:
            if family_slug(p.family) in repaired:
                continue
            host._log(state, parent.id, LogEntry(
                kind="error", title=f"Dropped a '{family_slug(p.family)}' hypothesis",
                text=f"{p.statement}\nIts edit could not be applied: " + "; ".join(problems)))
        for p, problems in still:
            host._log(state, parent.id, LogEntry(
                kind="error", title=f"Dropped a repaired '{family_slug(p.family)}' hypothesis",
                text=f"{p.statement}\nStill does not apply: " + "; ".join(problems)))
        return ok

    async def _create_and_score(self, host: RunManager, state: LiveRun, parent: Node,
                                base: str | None, kept: list) -> list[Node]:
        run = state.run
        earlier = [n.full_text() for n in state.nodes]
        ids = next_node_ids(state.nodes, len(kept))
        nodes = []
        for node_id, (p, edit, checked, family) in zip(ids, kept, strict=True):
            node = Node(
                id=node_id, run_id=run.id, parent_id=parent.id, depth=parent.depth + 1,
                type="hypothesis",
                description=" ".join(p.title.split())[:120] or short_title(p.statement),
                status="pending", phase="hypothesis", family=family,
                summary=p.statement,
                hypothesis=HypothesisSpec(statement=p.statement, rationale=p.rationale,
                                          family=family,
                                          planned_experiment=p.planned_experiment,
                                          expected_signal=p.expected_signal,
                                          measures=p.measures,
                                          queries=p.queries if checked is None else []),
                edit=edit, base_version=base, version=checked.version if checked else None)
            state.nodes.append(node)
            nodes.append(node)
            host._emit(state, NodeCreated, node=node)
            stats = edit.stats if edit else None
            detail = (f"\nChange: {stats.files} file(s), +{stats.added}/-{stats.removed} lines"
                      if stats else f"\nSearches: {'; '.join(p.queries)}" if p.queries else "")
            host._log(state, node.id, LogEntry(
                kind="decision", title="Proposed and validated",
                text=f"{p.statement}\nWhy: {p.rationale}\nExperiment: {p.planned_experiment}"
                     + detail
                     + ("\n" + "\n".join(checked.notes) if checked and checked.notes else ""),
                phase="hypothesis"))

        await host._checkpoint(state)
        scored = await self.prescorer.score_siblings(
            nodes, question=run.question, objectives=run.objectives, people=run.vault_people,
            parent=parent, dead_ends=state.dead_ends, earlier=earlier,
            instructions=run.instructions, directives=run.directives)
        for node, s in zip(nodes, scored, strict=True):
            pre.apply(node, s)
            node.pre_band = BANDS[s.zone]
            if s.duplicate_of and node.status != "parked":
                node.status = "parked"
                node.decision = Decision(verdict="park", stage="pre",
                                         reason=f"Repeats earlier work: {s.duplicate_of}")
            overall = to_ten(s.pre_score.overall)
            host._log(state, node.id, LogEntry(
                kind="decision", title=f"Pre-score {overall:.1f} / 10 ({node.pre_band})",
                text=node.decision.reason if node.decision else "", phase="hypothesis"))
            if node.status == "parked":
                state.dead_ends.append(DeadEnd(run_id=run.id, node_id=node.id,
                                               description=node.full_text(),
                                               reason=node.decision.reason
                                               if node.decision else "parked"))
            host._emit(state, NodeUpdated, node=node,
                       change="parked" if node.status == "parked" else "scored")
        return nodes
