"""The knowledge vault: people, the mind-map graph, single items, and ingestion."""

from fastapi import APIRouter, Query

from ..models import IngestRequest, VaultGraph, VaultItemView
from .common import not_implemented

router = APIRouter(prefix="/vault", tags=["vault"])


@router.get("/people")
async def list_people() -> list[str]:
    not_implemented("list_people")


@router.get("/graph")
async def get_graph(
    person: str | None = Query(None, description="Only this person's items; omit for everyone."),
) -> VaultGraph:
    """Items plus nearest-neighbor edges. Embeddings are never included."""
    not_implemented("get_graph")


@router.get("/items/{item_id}")
async def get_item(item_id: str) -> VaultItemView:
    not_implemented("get_item")


@router.post("/items", status_code=201)
async def ingest_item(body: IngestRequest) -> VaultItemView:
    """Ingest text: a cheaper LLM writes title, summary and tags, then it is embedded and
    linked to its nearest neighbors. Also announced as a vault_item_added event."""
    not_implemented("ingest_item")
