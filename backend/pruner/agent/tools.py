"""Tools the agent can call.

Rule: the agent only gets tools that read or propose. Anything that changes files or runs
commands is done by the orchestrator. So there is deliberately no edit tool (the agent's edit is
its output, which a validator checks and the orchestrator applies), no run tool (the
orchestrator runs experiments after pre-scoring, so pruning cannot be bypassed) and no shell tool.
If the agent's output fails validation, the orchestrator sends the error back for one retry; that
is a loop, not a tool.

Read-only tools (build them for one run with build_tools):
  search_vault(query)   the 2 closest notes, their contradicting/investigate links, and how
                        many notes support and how many agree with each (counted separately)
  get_results(status, contains, limit)   past results from this run's tree
  web_search(query, k)     titles, URLs and snippets (the search API is not chosen yet)
  fetch(url)               a public page's cleaned text, cached

Each tool takes keyword arguments matching its JSON schema and returns text (JSON) for the model.
A tool never raises for a bad call: it returns {"error": ...} so the model can correct itself.

Not built yet: the function-calling loop. The LLM wrapper only does structured output, so the
agent lists these tools in its prompt but cannot call them; DEFAULT_TOOLS stays empty until then.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pruner.agent.web import (
    FetchError,
    PageFetcher,
    SearchNotConfigured,
    SearchProvider,
    get_search_provider,
)
from pruner.core.config import Config, get_config
from pruner.core.models import Node, Run
from pruner.pruning.scale import to_ten
from pruner.vault.store import VaultStore, one_line

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments
    run: Callable[..., Awaitable[str]]

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
    return {"corroboration_note": f"In the vault this note is {' and '.join(parts)}; weigh it a "
                                  "bit higher (support counts for more than agreement)."}


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
        linked = {i for e in edges for i in (e.source, e.target)} - found
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
                             for i in sorted(linked) if (n := ctx.vault.get(i))],
        }
        if not hits:
            out["note"] = "No note is close enough to the query; rely on your own judgement."
        return _json(out)

    return Tool("search_vault",
                "Search the chosen people's notes by meaning. Returns the two closest notes if "
                "they are very close to the query, plus their links that matter: every "
                "'contradicts' and 'investigate' link, each with the reason. Notes reached only through "
                "a link are under linked_items. Each note also counts the other notes that support "
                "it (give evidence for it: supporting_notes) and that agree with it (same view, "
                "not evidence: agreeing_notes); a guide to weigh it a bit higher, not proof. "
                "Returns "
                "nothing when no note is close enough: then rely on your own judgement.",
                _schema({"query": {"type": "string"}}, ["query"]), search_vault)


def get_results_tool(ctx: ToolContext) -> Tool:
    async def get_results(status: str | None = None, contains: str | None = None,
                          limit: int = 10) -> str:
        found = []
        for n in ctx.nodes:
            if n.result is None or (status and n.status != status):
                continue
            if contains and contains.casefold() not in f"{n.description} {n.result}".casefold():
                continue
            found.append({
                "id": n.id, "parent_id": n.parent_id, "description": n.description,
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
                web: bool = False) -> tuple[Tool, ...]:
    """The tools for one run: vault and results by default, plus web_search and fetch for web
    research."""
    tools: list[Tool] = []
    if vault:
        tools.append(search_vault_tool(ctx))
    if results:
        tools.append(get_results_tool(ctx))
    if web:
        tools += [web_search_tool(ctx), fetch_tool(ctx)]
    return tuple(tools)
