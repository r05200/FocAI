"""Shared singletons for route handlers. Tests swap them with app.dependency_overrides."""

from functools import lru_cache

from pruner.runs.store import RunStore
from pruner.vault.directives import DirectiveStore
from pruner.vault.store import VaultStore


@lru_cache(maxsize=1)
def get_vault_store() -> VaultStore:
    return VaultStore()


@lru_cache(maxsize=1)
def get_directive_store() -> DirectiveStore:
    return DirectiveStore()


@lru_cache(maxsize=1)
def get_run_store() -> RunStore:
    return RunStore()
