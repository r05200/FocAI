"""The knowledge vault: people, the mind-map graph, single items, and ingestion."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from pruner.api.deps import get_vault_store
from pruner.core.llm import LLMError
from pruner.core.models import (
    CreateVaultRequest,
    IngestRequest,
    IngestResult,
    VaultGraph,
    VaultItemView,
    VaultSummary,
)
from pruner.vault.store import VaultExistsError, VaultStore

router = APIRouter(prefix="/vault", tags=["vault"])

Store = Annotated[VaultStore, Depends(get_vault_store)]


@router.get("/people")
async def list_people(store: Store) -> list[str]:
    return store.people()


@router.post("/vaults", status_code=201)
async def create_vault(body: CreateVaultRequest, store: Store) -> VaultSummary:
    """Create an empty vault for a person so they show up in /people before any item is added."""
    try:
        return store.create_vault(body.person)
    except VaultExistsError as e:
        raise HTTPException(status_code=409, detail=f"{body.person} already has a vault") from e


@router.get("/graph")
async def get_graph(
    store: Store,
    person: str | None = Query(None, description="Only this person's items; omit for everyone."),
) -> VaultGraph:
    """Items plus their links (with relation and reason). Embeddings are never included."""
    return store.graph(person)


@router.get("/items/{item_id}")
async def get_item(item_id: str, store: Store) -> VaultItemView:
    item = store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"vault item {item_id} not found")
    return item.view()


@router.post("/items", status_code=201)
async def ingest_item(body: IngestRequest, store: Store) -> IngestResult:
    """Ingest text: the vault LLM writes a title, summary blurb and tags; the item is embedded,
    linked to its nearest neighbors, and each link is labelled contradicts / supports / agrees /
    investigate (a question worth looking into) with a one-line reason. Neighbors judged
    unrelated get no link."""
    try:
        return await store.ingest(body)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
