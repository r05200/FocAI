"""Tools the agent can call (through Gemini function calling, see agent/toolloop.py).

Rule: the agent never changes the user's files or runs commands. Its edit is its output, which the
orchestrator checks and applies; experiments are run by the orchestrator after pre-scoring, so
pruning cannot be bypassed. So there is no edit, run or shell tool. If the agent's output fails
validation, the orchestrator sends the error back for one retry; that is a loop, not a tool.

Read tools (build them for one run with build_tools):
  search_vault(query)   the 2 closest notes, their contradicting/investigate links (at most
                        cfg.agent_linked_cap notes reached through a link), and how many notes
                        support and how many agree with each (counted separately)
  get_results(status, contains, limit)   past results from this run's tree
  read_file(path, start_line, end_line)  a file of the run's workspace, at the node's code version
  web_search(query, k)  titles, URLs and snippets (offered only once a search API is set up)
  fetch(url)            a public page's cleaned text, cached

Write tools: they only write the run's own records, never the user's files or the main vault.
  write_findings_log(text, verdict, evidence_node_ids)   a line in the run's shared findings log
  write_findings_vault(title, summary, branch_node_ids, confidence)   a whole-branch finding in
                        the run vault, accepted only when confidence >= cfg.
                        branch_finding_min_confidence and the branch has a supported, measured node

Every call also carries a required `reason` (added and logged by ToolRunner, not seen here).
Each tool takes keyword arguments matching its JSON schema and returns text (JSON) for the model.
A tool never raises for a bad call: it returns {"error": ...} so the model can correct itself.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pruner.agent.web import (
    FetchError,
    PageFetcher,
    SearchNotConfigured,
    SearchProvider,
    get_search_provider,
)
from pruner.core.config import Config, get_config
from pruner.core.models import Finding, HypothesisVerdict, Node, Run, RunIdea
from pruner.pruning.scale import to_ten
from pruner.vault.store import VaultStore, one_line
from pruner.workspace.paths import PathError

if TYPE_CHECKING:
    from pruner.workspace.workspace import Workspace

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments
    run: Callable[..., Awaitable[str]]
    kind: Literal["read", "write"] = "read"

    async def call(self, arguments: dict[str, Any]) -> str:
        """Run with the model's arguments; a bad call becomes an error the model can read."""
        try:
            return await self.run(**arguments)
        except TypeError as e:
            return _error(f"bad arguments for {self.name}: {e}")


DEFAULT_TOOLS: tuple[Tool, ...] = ()


@dataclass
class ToolContext:
    """What the tools may read for one run."""

    run: Run
    nodes: Sequence[Node]
    vault: VaultStore
    cfg: Config = field(default_factory=get_config)
    search: SearchProvider | None = None  # defaults to get_search_provider(cfg)
    fetcher: PageFetcher | None = None  # defaults to PageFetcher(cfg)
    retrieved: list[str] = field(default_factory=list)  # vault ids search_vault returned
    workspace: Workspace | None = None  # the user's files, for read_file
    version: str | None = None  # the code version read_file reads (the applied one if None)
    node_id: str | None = None  # the node the agent is working on
    # Where the write tools put what they write (set by the orchestrator).
    on_finding: Callable[[Finding], None] | None = None
    on_branch_finding: Callable[[RunIdea], None] | None = None


READ_FILE_MAX_CHARS = 8000
VERDICTS: tuple[HypothesisVerdict, ...] = ("supported", "refuted", "inconclusive")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _error(message: str) -> str:
    return _json({"error": message})


def _schema(properties: dict[str, Any], required: Sequence[str] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required)}


# --------------------------------------------------------------------------- the tools


def _corroboration_note(supports: int, agrees: int) -> dict[str, str]:
    """The guide text for a note's support and agreement counts ({} when it has neither)."""
    def notes(n: int) -> str:
        return f"{n} other note{'s' if n != 1 else ''}"

    parts = []
    if supports:
        parts.append(f"supported by {notes(supports)} (they give evidence for it)")
    if agrees:
        parts.append(f"agreed with by {notes(agrees)} (they reach the same view, which is weaker "
                     "than evidence)")
    if not parts:
        return {}
    return {"corroboration_note": f"In the vault this note is {' and '.join(parts)}; a somewhat "
                                  "stronger lead (support counts for more than agreement), but "
                                  "still an unverified note: other notes lining up does not make "
                                  "it true."}


def search_vault_tool(ctx: ToolContext) -> Tool:
    async def search_vault(query: str) -> str:
        if not query.strip():
            return _error("query is empty")
        [embedding] = await ctx.vault.llm.embed([query], task="RETRIEVAL_QUERY",
                                                purpose="agent_tool")
        hits = ctx.vault.nearest(embedding, k=ctx.cfg.agent_search_top,
                                 threshold=ctx.cfg.agent_search_threshold,
                                 people=ctx.run.vault_people)
        ctx.retrieved.extend(i.id for i, _ in hits)
        found = {i.id for i, _ in hits}
        all_edges = ctx.vault.edges_of(found, ctx.run.vault_people)
        # Corroboration, kept apart: how many other notes SUPPORT each found note (give evidence
        # for it) and how many AGREE with it (the same view, not evidence). A link counts for
        # both of its ends. A guide to weigh the note a bit higher, not a verdict.
        support = {r: {i: set() for i in found} for r in ("supports", "agrees")}
        for e in all_edges:
            if e.relation in support:
                for mine, other in ((e.source, e.target), (e.target, e.source)):
                    if mine in found:
                        support[e.relation][mine].add(other)
        # Links shown: every "contradicts" and every "investigate". Supports/agrees are only
        # counted above, not listed.
        edges = [e for e in all_edges if e.relation in ("contradicts", "investigate")]
        # Notes reached only through a link: at most agent_linked_cap, strongest links first.
        linked: list[str] = []
        for e in sorted(edges, key=lambda e: -e.weight):
            for i in (e.source, e.target):
                if i not in found and i not in linked and len(linked) < ctx.cfg.agent_linked_cap:
                    linked.append(i)
        edges = [e for e in edges if {e.source, e.target} <= found | set(linked)]
        out: dict[str, Any] = {
            "items": [{"id": i.id, "kind": i.kind, "person": i.person, "title": i.title,
                       "summary": i.summary, "tags": i.tags, "similarity": round(sim, 3),
                       "supporting_notes": len(support["supports"][i.id]),
                       "agreeing_notes": len(support["agrees"][i.id]),
                       **_corroboration_note(len(support["supports"][i.id]),
                                             len(support["agrees"][i.id]))}
                      for i, sim in hits],
            "edges": [{"source": e.source, "target": e.target, "relation": e.relation,
                       "reason": e.reason, "weight": e.weight} for e in edges],
            "linked_items": [{"id": i, "kind": n.kind, "person": n.person, "title": n.title,
                              "summary": n.summary}
                             for i in linked if (n := ctx.vault.get(i))],
        }
        if not hits:
            out["note"] = "No note is close enough to the query; rely on your own judgement."
        ctx.vault.record_retrieval([*(i.id for i, _ in hits),
                                    *(i["id"] for i in out["linked_items"])])
        return _json(out)

    return Tool("search_vault",
                "Search the chosen people's notes by meaning. Returns the two closest notes if "
                "they are very close to the query, plus their links that matter: every "
                "'contradicts' and 'investigate' link, each with the reason. Notes reached only through "
                "a link are under linked_items. Each note also counts the other notes that support "
                "it (give evidence for it: supporting_notes) and that agree with it (same view, "
                "not evidence: agreeing_notes); a guide to weigh it a bit higher, not proof. "
                "Notes are the user's own, not a source of truth: use them as leads and check "
                "them. Returns nothing when no note is close enough: then rely on your own "
                "judgement.",
                _schema({"query": {"type": "string"}}, ["query"]), search_vault)


def get_results_tool(ctx: ToolContext) -> Tool:
    async def get_results(status: str | None = None, contains: str | None = None,
                          limit: int = 10) -> str:
        found = []
        for n in ctx.nodes:
            if n.result is None or (status and n.status != status):
                continue
            if contains and contains.casefold() not in f"{n.full_text()} {n.result}".casefold():
                continue
            found.append({
                "id": n.id, "parent_id": n.parent_id, "description": n.full_text()[:400],
                "status": n.status, "result": one_line(n.result)[:800],
                "post_score": None if n.post_score is None else to_ten(n.post_score),
                "objectives_advanced": n.criteria_progress,
            })
        return _json(found[: max(1, min(int(limit), 50))])

    return Tool("get_results",
                "Past results from this run's tree, optionally only one status (done, parked, "
                "failed) or only those mentioning some text. post_score is on the 1 to 10 scale.",
                _schema({"status": {"type": "string", "enum": ["done", "parked", "failed",
                                                               "running", "pending"]},
                         "contains": {"type": "string"},
                         "limit": {"type": "integer", "minimum": 1, "maximum": 50}}),
                get_results)


def read_file_tool(ctx: ToolContext) -> Tool:
    async def read_file(path: str, start_line: int | None = None,
                        end_line: int | None = None) -> str:
        if ctx.workspace is None:
            return _error("this run has no files")
        try:
            text = ctx.workspace.read(path, ctx.version)
        except PathError as e:
            return _error(str(e))
        except KeyError as e:
            return _error(str(e))
        if text is None:
            return _error(f"{path} does not exist, is binary or too large, or is private")
        lines = text.splitlines()
        first = max(1, int(start_line or 1))
        last = min(len(lines), int(end_line or len(lines)))
        body = "\n".join(f"{n}: {line}" for n, line in enumerate(lines[first - 1:last], first))
        cut = len(body) > READ_FILE_MAX_CHARS
        return _json({"path": path, "lines": [first, last], "total_lines": len(lines),
                      "text": body[:READ_FILE_MAX_CHARS],
                      **({"note": "cut short; read a smaller line range"} if cut else {})})

    return Tool("read_file",
                "Read a file of this run's workspace (at the code version you are working on), "
                "with line numbers. Use start_line/end_line for long files.",
                _schema({"path": {"type": "string"},
                         "start_line": {"type": "integer", "minimum": 1},
                         "end_line": {"type": "integer", "minimum": 1}}, ["path"]),
                read_file)


def write_findings_log_tool(ctx: ToolContext) -> Tool:
    async def write_findings_log(text: str, verdict: str = "inconclusive",
                                 evidence_node_ids: list[str] | None = None) -> str:
        if ctx.on_finding is None:
            return _error("the findings log is not available here")
        if not text.strip():
            return _error("text is empty")
        if verdict not in VERDICTS:
            return _error(f"verdict must be one of {', '.join(VERDICTS)}")
        known = {n.id for n in ctx.nodes}
        unknown = [i for i in evidence_node_ids or [] if i not in known]
        if unknown:
            return _error(f"unknown node ids: {', '.join(unknown)}")
        family = next((n.family for n in ctx.nodes if n.id == ctx.node_id), None)
        finding = Finding(run_id=ctx.run.id, node_id=ctx.node_id, family=family,
                          verdict=verdict, text=one_line(text), source="agent_tool",
                          evidence_node_ids=list(evidence_node_ids or []))  # type: ignore[arg-type]
        ctx.on_finding(finding)
        return _json({"ok": True, "finding_id": finding.id})

    return Tool("write_findings_log",
                "Add one line to the run's shared findings log (what was learned, with the verdict "
                "and the nodes that show it). Later steps read this log.",
                _schema({"text": {"type": "string"},
                         "verdict": {"type": "string", "enum": list(VERDICTS)},
                         "evidence_node_ids": {"type": "array", "items": {"type": "string"}}},
                        ["text", "verdict"]),
                write_findings_log, kind="write")


def _branch(nodes: Sequence[Node], node_id: str) -> str:
    by_id = {n.id: n for n in nodes}
    path, current = [], by_id.get(node_id)
    while current is not None:
        path.append(current.id)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return " > ".join(reversed(path))


def write_findings_vault_tool(ctx: ToolContext) -> Tool:
    async def write_findings_vault(title: str, summary: str, branch_node_ids: list[str],
                                   confidence: float) -> str:
        if ctx.on_branch_finding is None:
            return _error("the run vault is not available here")
        if not title.strip() or not summary.strip():
            return _error("title and summary are required")
        by_id = {n.id: n for n in ctx.nodes}
        unknown = [i for i in branch_node_ids if i not in by_id]
        if not branch_node_ids or unknown:
            return _error(f"unknown node ids: {', '.join(unknown)}" if unknown
                          else "branch_node_ids is empty")
        minimum = ctx.cfg.branch_finding_min_confidence
        if float(confidence) < minimum:
            return _error(f"confidence {float(confidence):.2f} is below {minimum:.2f}: keep "
                          f"testing, or write a line to the findings log instead")
        nodes = [by_id[i] for i in branch_node_ids]
        if not any(n.verdict == "supported" and n.experiment and n.experiment.metrics
                   for n in nodes):
            return _error("no node of this branch has a supported, measured result yet")
        deepest = max(nodes, key=lambda n: n.depth)
        idea = RunIdea(branch=_branch(ctx.nodes, deepest.id), title=one_line(title),
                       summary=one_line(summary), kind="branch_finding",
                       confidence=round(float(confidence), 3), node_ids=list(branch_node_ids))
        ctx.on_branch_finding(idea)
        return _json({"ok": True, "idea_id": idea.id})

    return Tool("write_findings_vault",
                "Write a whole branch's conclusion to the run vault once you are fairly sure of it "
                "(it needs a supported, measured result on the branch). Give the branch's node "
                "ids and your confidence from 0 to 1.",
                _schema({"title": {"type": "string"}, "summary": {"type": "string"},
                         "branch_node_ids": {"type": "array", "items": {"type": "string"}},
                         "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
                        ["title", "summary", "branch_node_ids", "confidence"]),
                write_findings_vault, kind="write")


def web_search_tool(ctx: ToolContext) -> Tool:
    async def web_search(query: str, k: int = 5) -> str:
        if not query.strip():
            return _error("query is empty")
        try:
            provider = ctx.search or get_search_provider(ctx.cfg)
            hits = await provider.search(query, max(1, min(int(k), 10)))
        except SearchNotConfigured as e:
            return _error(str(e))
        except Exception as e:  # noqa: BLE001 - any provider failure: tell the agent, keep going
            log.error("500 server issue: the web search API call failed (%s: %s). If this keeps "
                      "happening, change SEARCH_API_KEY in .env.", type(e).__name__, e)
            return _error("web search failed; try again later or use other sources")
        return _json([h.model_dump() for h in hits])

    return Tool("web_search", "Search the web. Returns titles, URLs and snippets.",
                _schema({"query": {"type": "string"},
                         "k": {"type": "integer", "minimum": 1, "maximum": 10}}, ["query"]),
                web_search)


def fetch_tool(ctx: ToolContext) -> Tool:
    async def fetch(url: str) -> str:
        fetcher = ctx.fetcher or PageFetcher(ctx.cfg)
        try:
            page = await fetcher.fetch(url)
        except FetchError as e:
            return _error(str(e))
        if not 200 <= page.status < 300:
            return _error(f"{url} returned {page.status}")
        return _json({"url": page.url, "title": page.title,
                      "text": page.text[: ctx.cfg.fetch_max_chars]})

    return Tool("fetch",
                "Fetch a public web page and return its cleaned text. Quote excerpts from it "
                "word for word when citing it.",
                _schema({"url": {"type": "string"}}, ["url"]), fetch)


def build_tools(ctx: ToolContext, *, vault: bool = True, results: bool = True,
                files: bool = False, web: bool = False, findings_log: bool = False,
                findings_vault: bool = False) -> tuple[Tool, ...]:
    """The tools for one run: vault and results by default; read_file, web_search + fetch, and
    the two write tools when asked for."""
    tools: list[Tool] = []
    if vault:
        tools.append(search_vault_tool(ctx))
    if results:
        tools.append(get_results_tool(ctx))
    if files:
        tools.append(read_file_tool(ctx))
    if web:
        tools += [web_search_tool(ctx), fetch_tool(ctx)]
    if findings_log:
        tools.append(write_findings_log_tool(ctx))
    if findings_vault:
        tools.append(write_findings_vault_tool(ctx))
    return tuple(tools)


def phase_tools(ctx: ToolContext, phase: str) -> tuple[Tool, ...]:
    """The tools a phase is offered: hypothesis = vault, results, read_file when the run has
    files, web only when a search API is set up, and the findings log; synthesis = vault,
    results and both write tools."""
    if phase == "synthesis":
        return build_tools(ctx, findings_log=True, findings_vault=True)
    return build_tools(ctx, files=ctx.workspace is not None,
                       web=bool(ctx.cfg.search_provider.strip()), findings_log=True)
