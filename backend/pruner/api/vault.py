"""The knowledge vault: people, the mind-map graph, single items, and ingestion."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from pruner.api.deps import get_vault_store
from pruner.core.llm import LLMError
from pruner.core.models import (
    CreateVaultRequest,
    IngestRequest,
    IngestResult,
    MoveItemRequest,
    MoveItemsRequest,
    RegenerateLayoutRequest,
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


@router.get("/vaults")
async def list_vaults(store: Store) -> list[VaultSummary]:
    """Every vault with its item count (empty vaults included)."""
    return [store.summary(p) for p in store.people()]


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


@router.patch("/items/{item_id}/position", status_code=204)
async def move_item(item_id: str, body: MoveItemRequest, store: Store) -> None:
    """The move tool: save where a card now sits on the map (item.position)."""
    try:
        store.move(item_id, body.x, body.y, body.z)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"vault item {item_id} not found") from e


@router.patch("/positions", status_code=204)
async def move_items(body: MoveItemsRequest, store: Store) -> None:
    """Save several moves at once. Unknown ids reject the whole request (404)."""
    try:
        store.move_many(body.positions)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"vault item {e.args[0]} not found") from e


@router.post("/layout/regenerate")
async def regenerate_layout(body: RegenerateLayoutRequest, store: Store) -> VaultGraph:
    """Recompute every automatic position (similar items close together). Spots a person set
    with the move tool are kept unless reset_moved. Returns the graph."""
    return store.regenerate_layout(body.reset_moved)


@router.post("/items", status_code=201)
async def ingest_item(body: IngestRequest, store: Store) -> IngestResult:
    """Ingest text: the vault LLM writes a title and summary blurb (tags are the ones you send); the item is embedded,
    linked to its nearest neighbors, and each link is labelled contradicts / supports / agrees /
    investigate (a question worth looking into) with a one-line reason. Neighbors judged
    unrelated get no link."""
    try:
        return await store.ingest(body)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
