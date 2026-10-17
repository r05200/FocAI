"""Shared singletons for route handlers. Tests swap them with app.dependency_overrides."""

from functools import lru_cache

from ..vault import VaultStore


@lru_cache(maxsize=1)
def get_vault_store() -> VaultStore:
    return VaultStore()
