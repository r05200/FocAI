import dataclasses

import pytest

from pruner.core.config import get_config
from pruner.vault.store import VaultStore
from tests.fakes import DIM, FakeLLM


@pytest.fixture
def cfg(tmp_path):
    return dataclasses.replace(
        get_config(),
        data_dir=tmp_path, cache_dir=tmp_path / "cache", vault_dir=tmp_path / "vaults",
        embedding_dim=DIM, link_threshold=0.3, neighbors_per_item=3,
        # Scoring thresholds pinned here (1 to 10 scale), so tests never depend on the environment.
        pre_score_min=2.0, run_score_min=6.0, post_score_min=4.0, rescore_park_below=4.0,
    )


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def store(cfg, fake_llm):
    return VaultStore(cfg.vault_dir, fake_llm, cfg)  # type: ignore[arg-type]
