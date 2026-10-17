"""Directives: a person's standing instructions, kept in their own tab of the vault."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from pruner.api.deps import get_directive_store
from pruner.core.models import Directive, DirectiveRequest
from pruner.vault.directives import DirectiveStore

router = APIRouter(prefix="/vault/directives", tags=["vault"])

Store = Annotated[DirectiveStore, Depends(get_directive_store)]


@router.get("")
async def list_directives(
    store: Store,
    person: str | None = Query(None, description="Only this person's directives."),
) -> list[Directive]:
    return store.list(person)


@router.post("", status_code=201)
async def add_directive(body: DirectiveRequest, store: Store) -> Directive:
    """File a directive. Stored as given: no LLM, embedding or links."""
    return store.add(body)


@router.delete("/{directive_id}", status_code=204)
async def delete_directive(directive_id: str, store: Store) -> None:
    if not store.delete(directive_id):
        raise HTTPException(status_code=404, detail="directive not found")
