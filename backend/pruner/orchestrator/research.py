"""The experiment phase of a research run (a run without files). No LLM decides anything here.

A research hypothesis is a guess about what the user wants to see, with 1-3 search queries.
Its experiment finds the resources:
  1. the vault: the queries are embedded and the closest notes of the run's vault people are
     taken (cfg.similarity_threshold, cfg.search_top_k per query; a VaultRetrieved event each);
  2. the web, when a search API is set up (PRUNER_SEARCH_PROVIDER): cfg.research_hits_per_query
     results per query; the text of the top cfg.research_fetch_pages pages is fetched as an
     excerpt (public pages only, cached);
  3. the result is the list of resources, with counts as metrics (resources, vault_hits,
     web_hits, top_similarity). Nothing found makes the experiment fail ("no resources found").
Whether the resources are relevant to the objectives is the synthesis step's judgement
(orchestrator/synthesis.py, synthesize_research.md), just as a command's numbers are.
With cfg.experiment_cache on, the same searches are not run twice.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from pruner.agent.web import (
    FetchError,
    PageFetcher,
    SearchNotConfigured,
    SearchProvider,
    get_search_provider,
)
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM, DiskCache
from pruner.core.models import ExperimentRun, Node, Run
from pruner.orchestrator.experiment import experiment_cache
from pruner.vault.store import VaultStore

EXCERPT_CHARS = 1500
# (people, query, item ids, similarities) for each vault search
OnRetrieved = Callable[[list[str], str, list[str], list[float]], None]


def queries_of(node: Node, cfg: Config) -> list[str]:
    asked = node.hypothesis.queries if node.hypothesis else []
    queries = [q.strip() for q in asked if q.strip()][: cfg.research_queries_max]
    return queries or [node.summary or node.description]


def search_people(run: Run) -> list[str]:
    """Whose vaults a research run searches: its vault people, or the run's owner."""
    return list(run.vault_people) or [run.primary_person]


class ResearchPhase:
    def __init__(self, vault: VaultStore | None, embedder: LLM | None,
                 cfg: Config | None = None, search: SearchProvider | None = None,
                 fetcher: PageFetcher | None = None) -> None:
        self.cfg = cfg or get_config()
        self.vault, self.embedder = vault, embedder
        self.search, self.fetcher = search, fetcher
        self.cache = experiment_cache(self.cfg)

    def web_ready(self) -> bool:
        return self.search is not None or bool(self.cfg.search_provider.strip())

    async def run(self, run: Run, node: Node,
                  on_retrieved: OnRetrieved | None = None) -> ExperimentRun:
        queries = queries_of(node, self.cfg)
        people = search_people(run)
        key = DiskCache.key({"kind": "research", "queries": queries, "people": people,
                             "provider": self.cfg.search_provider if self.web_ready() else ""})
        if self.cache is not None and (hit := self.cache.get(key)) is not None:
            return ExperimentRun.model_validate({**hit, "cached": True})
        started = time.monotonic()
        notes: list[str] = []
        resources = await self._vault(queries, people, on_retrieved)
        vault_hits = len(resources)
        if self.web_ready():
            resources += await self._web(queries, notes)
        else:
            notes.append("web search is not set up (PRUNER_SEARCH_PROVIDER), so only the vault "
                         "was searched")
        web_hits = len(resources) - vault_hits
        exp = ExperimentRun(
            command="search: " + "; ".join(queries), exit_code=0,
            duration_s=round(time.monotonic() - started, 2),
            result={"queries": queries, "resources": resources, "notes": notes},
            metrics={"resources": float(len(resources)), "vault_hits": float(vault_hits),
                     "web_hits": float(web_hits),
                     "top_similarity": max((r["similarity"] for r in resources
                                            if r["source"] == "vault"), default=0.0)})
        if not resources:
            exp.error = "no resources found" + (f" ({notes[0]})" if notes else "")
        elif self.cache is not None:
            self.cache.set(key, exp.model_dump())
        return exp

    async def _vault(self, queries: list[str], people: list[str],
                     on_retrieved: OnRetrieved | None) -> list[dict]:
        if self.vault is None or self.embedder is None:
            return []
        vectors = await self.embedder.embed(queries, task="RETRIEVAL_QUERY",
                                            purpose="research_embed")
        found: dict[str, dict] = {}
        for query, vector in zip(queries, vectors, strict=True):
            hits = self.vault.nearest(vector, k=self.cfg.search_top_k,
                                      threshold=self.cfg.similarity_threshold, people=people)
            if on_retrieved is not None:
                on_retrieved(people, query, [i.id for i, _ in hits],
                             [round(float(s), 4) for _, s in hits])
            for item, sim in hits:
                if item.id not in found or found[item.id]["similarity"] < sim:
                    found[item.id] = {"source": "vault", "id": item.id, "person": item.person,
                                      "kind": item.kind, "title": item.title,
                                      "summary": item.summary,
                                      "similarity": round(float(sim), 4), "query": query}
        return sorted(found.values(), key=lambda r: -r["similarity"])

    async def _web(self, queries: list[str], notes: list[str]) -> list[dict]:
        try:
            provider = self.search or get_search_provider(self.cfg)
        except SearchNotConfigured as e:
            notes.append(str(e))
            return []
        found: dict[str, dict] = {}
        for query in queries:
            try:
                hits = await provider.search(query, self.cfg.research_hits_per_query)
            except SearchNotConfigured as e:
                notes.append(str(e))
                return list(found.values())
            except Exception as e:  # noqa: BLE001 - a provider failure is a note, not a crash
                notes.append(f"web search failed for {query!r} ({type(e).__name__})")
                continue
            for h in hits:
                found.setdefault(h.url, {"source": "web", "url": h.url, "title": h.title,
                                         "snippet": h.snippet, "query": query})
        resources = list(found.values())
        fetcher = self.fetcher or PageFetcher(self.cfg)
        for r in resources[: self.cfg.research_fetch_pages]:
            try:
                page = await fetcher.fetch(r["url"])
            except FetchError:
                continue
            if 200 <= page.status < 300 and page.text:
                r["excerpt"] = page.text[:EXCERPT_CHARS]
        return resources
