"""The knowledge vault: ingestion, storage, similarity links and relation labels.

Ingest pipeline for one item:
  1. The vault LLM writes a title and a short summary blurb (it no longer writes tags: those
     come from the person, via IngestRequest.tags).
  2. The item is embedded.
  3. Its nearest existing items (any person) with cosine similarity >= cfg.link_threshold,
     at most cfg.neighbors_per_item of them, become candidate links.
  4. The vault LLM labels each link contradicts / supports / agrees / investigate / unrelated,
     with a one-line reason; any link with a question on either end is forced to "investigate".
     Pairs judged "unrelated" (or not judged) get no edge.

Each item also carries two spots on the 3D mind map, cached with it: auto_position (the
backend's layout: a new item goes beside its most similar neighbor, items loaded without one are
laid out when the store starts, regenerate_layout() recomputes all of them) and position (only
set when a person moved the card with the move tool, and never touched by a regeneration unless
asked). See layout.py.

Storage: data/vaults/<person>.json holds that person's items (with embeddings and positions);
data/vaults/_edges.json holds every edge. Files are rewritten atomically after each change.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from pruner.agent.web import PageFetcher
from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.fs import write_atomic
from pruner.core.llm import LLM
from pruner.core.models import (
    IngestRequest,
    IngestResult,
    ItemPosition,
    Position,
    VaultEdge,
    VaultGraph,
    VaultItem,
    VaultJudgement,
    VaultSummary,
)
from pruner.vault import layout
from pruner.vault.links import NO_SUMMARY, fetch_paper, link_of

log = logging.getLogger(__name__)

EDGES_FILE = "_edges.json"
MAX_INGEST_CHARS = 12_000  # long texts are truncated before they reach the LLM
MAX_TAGS = 5
EMBEDDING_DIGITS = 4  # significant digits kept per stored embedding value (similarity shifts < 1e-4)


# --------------------------------------------------------------------------- LLM output shapes


class IngestDraft(BaseModel):
    title: str
    summary: str
    investigate: bool = False


class RelationJudgement(BaseModel):
    neighbor_id: str
    relation: VaultJudgement
    reason: str


class RelationOutput(BaseModel):
    relations: list[RelationJudgement] = Field(default_factory=list)


# --------------------------------------------------------------------------- helpers


class VaultExistsError(ValueError):
    """The person already has a vault."""


def normalize_tag(tag: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", tag.strip().lower()).strip("-")


def wants_investigation(item: VaultItem) -> bool:
    return item.kind == "question" or item.investigate


def one_line(text: str) -> str:
    return " ".join(text.split())


def unit_vectors(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def round_embedding(vector: list[float]) -> list[float]:
    """Keep EMBEDDING_DIGITS significant digits per value: about 30% smaller files, and cosine
    similarities move by less than 0.0001."""
    return [float(f"{v:.{EMBEDDING_DIGITS}g}") for v in vector]


def _items_json(items: list[dict]) -> str:
    """Indented for reading, except each embedding sits on one line (they are long and never
    edited by hand)."""
    held = [round_embedding(e) if (e := item.get("embedding")) is not None else None
            for item in items]
    shown = [{**item, "embedding": f"__embedding_{i}__"} if item.get("embedding") is not None
             else item for i, item in enumerate(items)]
    text = json.dumps(shown, indent=1)
    for i, emb in enumerate(held):
        if emb is not None:
            text = text.replace(f'"__embedding_{i}__"', json.dumps(emb, separators=(",", ":")))
    return text


def embedding_text(item: VaultItem) -> str:
    return f"{item.title}\n{item.summary}\n{item.source_text[:MAX_INGEST_CHARS]}"


# --------------------------------------------------------------------------- store


class VaultStore:
    def __init__(self, directory: Path | None = None, llm: LLM | None = None,
                 cfg: Config | None = None, fetcher: PageFetcher | None = None) -> None:
        self.cfg = cfg or get_config()
        self.fetcher = fetcher or PageFetcher(self.cfg)  # reads paper links (vault/links.py)
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
        for person in self._lay_out_missing():  # e.g. seeded items that were never placed
            self._save(person)

    def _save(self, person: str) -> None:
        items = [i.model_dump(mode="json") for i in self._items.values() if i.person == person]
        write_atomic(self.dir / f"{person}.json", _items_json(items))
        write_atomic(self.dir / EDGES_FILE,
                     json.dumps([e.model_dump(mode="json") for e in self._edges], indent=1))

    # ---- layout (positions are cached on the items)

    def _placed(self) -> list[tuple[list[float], tuple[float, float, float]]]:
        """Embedding and current spot (moved by hand, else automatic) of every placed item."""
        placed = []
        for i in self._items.values():
            spot = i.position or i.auto_position
            if spot and i.embedding is not None:
                placed.append((i.embedding, (spot.x, spot.y, spot.z)))
        return placed

    def _apply_pca(self, reset_moved: bool) -> set[str]:
        """Recompute auto_position for every item with an embedding (and forget manual moves
        if reset_moved). Returns the owners whose items changed."""
        items = [i for i in self._items.values() if i.embedding is not None]
        spots = layout.pca_positions([i.id for i in items],
                                     np.array([i.embedding for i in items], dtype=np.float32))
        owners = set()
        for item in items:
            x, y, z = spots[item.id]
            item.auto_position = Position(x=x, y=y, z=z)
            if reset_moved:
                item.position = None
            owners.add(item.person)
        return owners

    def _lay_out_missing(self) -> set[str]:
        """Give every item without an auto_position one. Returns the owners that changed."""
        missing = sorted((i for i in self._items.values()
                          if i.auto_position is None and i.embedding is not None),
                         key=lambda i: i.created_at)
        if not missing:
            return set()
        placed = self._placed()
        if not placed:  # nothing laid out yet: a full layout for everyone
            return self._apply_pca(reset_moved=False)
        for item in missing:
            x, y, z = layout.place_near(item.id, item.embedding, placed)  # type: ignore[arg-type]
            item.auto_position = Position(x=x, y=y, z=z)
            placed.append((item.embedding, (x, y, z)))  # type: ignore[arg-type]
        return {i.person for i in missing}

    def move(self, item_id: str, x: float, y: float, z: float) -> VaultItem:
        """The move tool: save where a card was moved to. Raises KeyError if there is no such
        item."""
        return self.move_many([ItemPosition(id=item_id, x=x, y=y, z=z)])[0]

    def move_many(self, moves: list[ItemPosition]) -> list[VaultItem]:
        """Save several moves at once. Nothing changes if any id is unknown (KeyError)."""
        unknown = [m.id for m in moves if m.id not in self._items]
        if unknown:
            raise KeyError(unknown[0])
        moved = []
        for m in moves:
            item = self._items[m.id]
            item.position = Position(x=m.x, y=m.y, z=m.z)
            moved.append(item)
        for person in {i.person for i in moved}:
            self._save(person)
        return moved

    def regenerate_layout(self, reset_moved: bool = False) -> VaultGraph:
        """Recompute every automatic position (similar items close together), save, and return
        the graph. Positions people set by hand stay unless reset_moved."""
        for person in self._apply_pca(reset_moved):
            self._save(person)
        return self.graph()

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
        write_atomic(self.dir / f"{person}.json", "[]")
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
                people: Collection[str] | None = None) -> list[tuple[VaultItem, float]]:
        """Top-k items by cosine similarity, at or above threshold, best first. `people` limits
        the search to those owners (an empty `people` searches nothing)."""
        pool = [i for i in self._items.values()
                if i.embedding is not None and (people is None or i.person in people)]
        if not pool:
            return []
        matrix = unit_vectors(np.array([i.embedding for i in pool], dtype=np.float32))
        sims = matrix @ unit_vectors(np.array(embedding, dtype=np.float32))
        order = np.argsort(-sims)[:k]
        return [(pool[j], float(sims[j])) for j in order if sims[j] >= threshold]

    def delete_item(self, item_id: str) -> bool:
        """Remove an item and its links (undoing a fork removes what deleted nodes learned)."""
        item = self._items.pop(item_id, None)
        if item is None:
            return False
        self._edges = [e for e in self._edges if item_id not in (e.source, e.target)]
        self._save(item.person)
        return True

    def record_retrieval(self, item_ids: Iterable[str]) -> None:
        """Count one retrieval for every id in `item_ids` (repeat an id to count it again): the
        notes an LLM was just shown, whether the agent's tool, a scorer or a research search
        took them out of the vault. Saved at once. Unknown ids are ignored. (Looking up an
        ingested item's neighbors to label its links is not a retrieval.)"""
        people = set()
        for item_id in item_ids:
            if (item := self._items.get(item_id)) is not None:
                item.retrieval_count += 1
                people.add(item.person)
        for person in people:
            self._save(person)

    def edges_of(self, item_ids: Collection[str],
                 people: Collection[str] | None = None) -> list[VaultEdge]:
        """The direct edges (either direction) of the given items. With `people`, only edges
        whose two items both belong to those people."""
        ids = set(item_ids)
        out = []
        for e in self._edges:
            if e.source not in ids and e.target not in ids:
                continue
            a, b = self._items.get(e.source), self._items.get(e.target)
            if a is None or b is None:
                continue
            if people is None or (a.person in people and b.person in people):
                out.append(e)
        return out

    # ---- ingest

    async def ingest(self, req: IngestRequest) -> IngestResult:
        if (link := link_of(req.text)) is not None:
            return await self._ingest_link(req, link)
        async with self._lock:
            text = req.text.strip()[:MAX_INGEST_CHARS]
            draft = (await self.llm.generate(
                IngestDraft,
                prompts.render("vault_ingest", kind=req.kind, text=text),
                model=self.cfg.vault_model, purpose="vault_ingest",
            )).value

            tags = list(dict.fromkeys(t for t in map(normalize_tag, req.tags) if t))[:MAX_TAGS]
            item = VaultItem(
                person=req.person, kind=req.kind, title=one_line(req.title or draft.title),
                summary=one_line(draft.summary), tags=tags, source_text=req.text.strip(),
                investigate=draft.investigate,
            )
            return await self._file(item)

    async def _ingest_link(self, req: IngestRequest, link: str) -> IngestResult:
        """A link instead of text: fetch the page and let the vault LLM take the abstract from
        it. No abstract, or a page that cannot be read: the summary says "No summary found"."""
        page = await fetch_paper(self.fetcher, link)
        if page.problem:
            draft = IngestDraft(title=link, summary=f"{NO_SUMMARY} ({page.problem}).")
            source = link
        else:
            text = page.text[:MAX_INGEST_CHARS]
            draft = (await self.llm.generate(
                IngestDraft,
                prompts.render("vault_ingest_link", kind=req.kind, url=link,
                               page_title=page.title or "(none)", text=text),
                model=self.cfg.vault_model, purpose="vault_ingest",
            )).value
            draft.summary = one_line(draft.summary) or f"{NO_SUMMARY}."
            draft.title = one_line(draft.title) or page.title or link
            source = f"{link}\n\n{text}"
        tags = list(dict.fromkeys(t for t in map(normalize_tag, req.tags) if t))[:MAX_TAGS]
        async with self._lock:
            item = VaultItem(
                person=req.person, kind=req.kind, title=one_line(req.title or draft.title),
                summary=one_line(draft.summary), tags=tags, source_text=source,
                investigate=False,
            )
            return await self._file(item)

    async def ingest_learned(self, person: str, title: str, summary: str,
                             source_text: str = "",
                             kind: Literal["learned", "correction"] = "learned") -> IngestResult:
        """File something a run learned (kind "learned"), or a person's correction of the run
        (kind "correction", e.g. restoring a parked branch). The title and summary are already
        written, so no draft LLM call is made: only the embedding and the link labels."""
        async with self._lock:
            item = VaultItem(person=person, kind=kind, title=one_line(title),
                             summary=one_line(summary),
                             source_text=(source_text or summary).strip()[:MAX_INGEST_CHARS])
            return await self._file(item)

    async def _file(self, item: VaultItem) -> IngestResult:
        """Embed a new item, link it to its neighbors, place it and save it (lock held)."""
        [vector] = await self.llm.embed([embedding_text(item)], purpose="vault_embed")
        item.embedding = round_embedding(vector)

        neighbors = self.nearest(item.embedding, k=self.cfg.neighbors_per_item,
                                 threshold=self.cfg.link_threshold)
        edges = await self._relate(item, neighbors)

        x, y, z = layout.place_near(item.id, item.embedding, self._placed())
        item.auto_position = Position(x=x, y=y, z=z)
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
