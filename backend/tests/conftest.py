import dataclasses

import pytest

from pruner.config import get_config
from pruner.vault import VaultStore
from tests.fakes import DIM, FakeLLM


@pytest.fixture
def cfg(tmp_path):
    return dataclasses.replace(
        get_config(),
        data_dir=tmp_path, cache_dir=tmp_path / "cache", vault_dir=tmp_path / "vaults",
        embedding_dim=DIM, link_threshold=0.3, neighbors_per_item=3,
    )


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def store(cfg, fake_llm):
    return VaultStore(cfg.vault_dir, fake_llm, cfg)  # type: ignore[arg-type]
