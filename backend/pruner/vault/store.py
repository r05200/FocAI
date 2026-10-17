"""The knowledge vault: ingestion, storage, similarity links and relation labels.

Ingest pipeline for one item:
  1. The vault LLM writes a title, a short summary blurb and tags (reusing existing tags).
  2. The item is embedded.
  3. Its nearest existing items (any person) with cosine similarity >= cfg.link_threshold,
     at most cfg.neighbors_per_item of them, become candidate links.
  4. The vault LLM labels each link contradicts / supports / agrees / investigate / unrelated,
     with a one-line reason; any link with a question on either end is forced to "investigate".
     Pairs judged "unrelated" (or not judged) get no edge.

Storage: data/vaults/<person>.json holds that person's items (with embeddings);
data/vaults/_edges.json holds every edge. Files are rewritten atomically after each ingest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Collection
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM
from pruner.core.models import (
    IngestRequest,
    IngestResult,
    VaultEdge,
    VaultGraph,
    VaultItem,
    VaultJudgement,
    VaultSummary,
)

log = logging.getLogger(__name__)

EDGES_FILE = "_edges.json"
MAX_INGEST_CHARS = 12_000  # long texts are truncated before they reach the LLM
MAX_TAGS = 5


# --------------------------------------------------------------------------- LLM output shapes


class VaultExistsError(ValueError):
    """The person already has a vault."""


class IngestDraft(BaseModel):
    title: str
    summary: str
    tags: list[str]
    investigate: bool = False


class RelationJudgement(BaseModel):
    neighbor_id: str
    relation: VaultJudgement
    reason: str


class RelationOutput(BaseModel):
    relations: list[RelationJudgement] = Field(default_factory=list)


# --------------------------------------------------------------------------- helpers


def normalize_tag(tag: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", tag.strip().lower()).strip("-")


def wants_investigation(item: VaultItem) -> bool:
    return item.kind == "question" or item.investigate


def one_line(text: str) -> str:
    return " ".join(text.split())


def unit_vectors(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def embedding_text(item: VaultItem) -> str:
    return f"{item.title}\n{item.summary}\n{item.source_text[:MAX_INGEST_CHARS]}"


# --------------------------------------------------------------------------- store


class VaultStore:
    def __init__(self, directory: Path | None = None, llm: LLM | None = None,
                 cfg: Config | None = None) -> None:
        self.cfg = cfg or get_config()
        self.dir = directory or self.cfg.vault_dir
        self.llm = llm or LLM(self.cfg)
        self._items: dict[str, VaultItem] = {}
        self._edges: list[VaultEdge] = []
        self._vaults: set[str] = set()  # every person with a vault, even an empty one
        self._lock = asyncio.Lock()  # one ingest at a time, so neighbors are never missed
        self._load()

    # ---- persistence

    def _load(self) -> None:
        if not self.dir.exists():
            return
        for path in sorted(self.dir.glob("*.json")):
            if path.name.startswith("_"):  # _edges.json, _directives.json: not item files
                continue
            self._vaults.add(path.stem)
            for raw in json.loads(path.read_text()):
                item = VaultItem.model_validate(raw)
                self._items[item.id] = item
        edges_path = self.dir / EDGES_FILE
        if edges_path.exists():
            self._edges = [VaultEdge.model_validate(e) for e in json.loads(edges_path.read_text())]

    def _write(self, path: Path, data: object) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)

    def _save(self, person: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        items = [i.model_dump(mode="json") for i in self._items.values() if i.person == person]
        self._write(self.dir / f"{person}.json", items)
        self._write(self.dir / EDGES_FILE, [e.model_dump(mode="json") for e in self._edges])

    # ---- reads

    def people(self) -> list[str]:
        return sorted(self._vaults | {i.person for i in self._items.values()})

    def summary(self, person: str) -> VaultSummary:
        return VaultSummary(person=person,
                            item_count=sum(i.person == person for i in self._items.values()))

    def create_vault(self, person: str) -> VaultSummary:
        """Create an empty vault for a person (stored as data/vaults/<person>.json).
        Raises VaultExistsError if they already have one. Ingesting into a person who has no
        vault still creates it implicitly."""
        if person in self.people():
            raise VaultExistsError(person)
        self._vaults.add(person)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._write(self.dir / f"{person}.json", [])
        return self.summary(person)

    def tags(self) -> list[str]:
        return sorted({t for i in self._items.values() for t in i.tags})

    def get(self, item_id: str) -> VaultItem | None:
        return self._items.get(item_id)

    def graph(self, person: str | None = None) -> VaultGraph:
        items = [i for i in self._items.values() if person is None or i.person == person]
        ids = {i.id for i in items}
        edges = [e for e in self._edges if e.source in ids and e.target in ids]
        return VaultGraph(nodes=[i.view() for i in items], edges=edges)

    def nearest(self, embedding: list[float], *, k: int, threshold: float,
                exclude: frozenset[str] = frozenset(), person: str | None = None,
                people: Collection[str] | None = None,
                ) -> list[tuple[VaultItem, float]]:
        """Top-k items by cosine similarity, at or above threshold, best first. `person` or
        `people` limits the search to those owners (an empty `people` searches nothing)."""
        pool = [i for i in self._items.values()
                if i.embedding is not None and i.id not in exclude
                and (person is None or i.person == person)
                and (people is None or i.person in people)]
        if not pool:
            return []
        matrix = unit_vectors(np.array([i.embedding for i in pool], dtype=np.float32))
        sims = matrix @ unit_vectors(np.array(embedding, dtype=np.float32))
        order = np.argsort(-sims)[:k]
        return [(pool[j], float(sims[j])) for j in order if sims[j] >= threshold]

    # ---- ingest

    async def ingest(self, req: IngestRequest) -> IngestResult:
        async with self._lock:
            text = req.text.strip()[:MAX_INGEST_CHARS]
            draft = (await self.llm.generate(
                IngestDraft,
                prompts.render("vault_ingest", kind=req.kind, text=text,
                               existing_tags=", ".join(self.tags()) or "(none yet)"),
                model=self.cfg.vault_model, purpose="vault_ingest",
            )).value

            tags = list(dict.fromkeys(t for t in map(normalize_tag, draft.tags) if t))[:MAX_TAGS]
            item = VaultItem(
                person=req.person, kind=req.kind, title=one_line(req.title or draft.title),
                summary=one_line(draft.summary), tags=tags, source_text=req.text.strip(),
                investigate=draft.investigate,
            )
            [item.embedding] = await self.llm.embed([embedding_text(item)],
                                                    purpose="vault_embed")

            neighbors = self.nearest(item.embedding, k=self.cfg.neighbors_per_item,
                                     threshold=self.cfg.link_threshold)
            edges = await self._relate(item, neighbors)

            self._vaults.add(item.person)
            self._items[item.id] = item
            self._edges.extend(edges)
            self._save(item.person)
            log.info("ingested %s (%s) with %d edges", item.id, item.title, len(edges))
            return IngestResult(item=item.view(), edges=edges)

    async def _relate(self, item: VaultItem,
                      neighbors: list[tuple[VaultItem, float]]) -> list[VaultEdge]:
        if not neighbors:
            return []
        listing = "\n".join(
            f"{n.id} ({n.kind}, {n.person}): {n.title}. {n.summary}" for n, _ in neighbors
        )
        out = (await self.llm.generate(
            RelationOutput,
            prompts.render("vault_relate", new_kind=item.kind, new_person=item.person,
                           new_title=item.title, new_summary=item.summary, neighbors=listing),
            model=self.cfg.vault_model, purpose="vault_relate",
        )).value

        judged = {j.neighbor_id: j for j in out.relations}
        edges = []
        for n, sim in neighbors:
            j = judged.get(n.id)
            if j is None:
                log.warning("vault LLM gave no relation for neighbor %s; no edge", n.id)
            elif j.relation != "unrelated":
                # Any link touching a question or a lead is something to look into, whatever the
                # LLM said.
                relation = ("investigate" if wants_investigation(item) or wants_investigation(n)
                            else j.relation)
                edges.append(VaultEdge(source=item.id, target=n.id, weight=round(sim, 4),
                                       relation=relation, reason=one_line(j.reason)))
        return edges
