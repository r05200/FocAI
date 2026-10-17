"""Single place for model names, thresholds, caps and paths.

Everything is overridable with a PRUNER_* environment variable (or a .env file at the repo
root), so tuning during the hackathon never means editing code.

NOTE: the Gemini model names below are defaults only. They have NOT been checked against the
models this API key can access; verify that in the LLM wrapper step before relying on them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(f"PRUNER_{name}", default)


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


@dataclass(frozen=True)
class Config:
    # --- LLM (provider-swappable; only llm.py reads these) ---
    gemini_api_key: str
    fast_model: str  # scoring and ingestion
    strong_model: str  # planning and synthesis
    embedding_model: str
    temperature: float

    # --- Agent caps (PRD: depth ~4, branching ~3, ~25 nodes) ---
    max_depth: int
    branching: int
    node_budget: int

    # --- Scoring thresholds (all 0..1, to be tuned on the demo question) ---
    pre_score_min: float  # candidates scoring below this are dropped before running
    post_score_min: float  # results scoring below this (and advancing no criterion) are pruned
    borderline_low: float  # scores in [low, high] trigger an ask-the-human question (P1)
    borderline_high: float

    # --- Vault ---
    similarity_threshold: float  # below this, vault search returns nothing
    search_top_k: int
    neighbors_per_item: int  # edges per node in the mind map

    # --- API ---
    cors_origins: tuple[str, ...]  # the Vite dev server by default

    # --- Paths ---
    data_dir: Path
    cache_dir: Path
    vault_dir: Path
    runs_dir: Path
    replays_dir: Path
    prompts_dir: Path


@lru_cache(maxsize=1)
def get_config() -> Config:
    data_dir = Path(_env("DATA_DIR", str(REPO_ROOT / "data")))
    return Config(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        fast_model=_env("FAST_MODEL", "gemini-2.5-flash-lite"),
        strong_model=_env("STRONG_MODEL", "gemini-2.5-pro"),
        embedding_model=_env("EMBEDDING_MODEL", "gemini-embedding-001"),
        temperature=_env_float("TEMPERATURE", 0.1),
        max_depth=_env_int("MAX_DEPTH", 4),
        branching=_env_int("BRANCHING", 3),
        node_budget=_env_int("NODE_BUDGET", 25),
        pre_score_min=_env_float("PRE_SCORE_MIN", 0.4),
        post_score_min=_env_float("POST_SCORE_MIN", 0.4),
        borderline_low=_env_float("BORDERLINE_LOW", 0.4),
        borderline_high=_env_float("BORDERLINE_HIGH", 0.6),
        similarity_threshold=_env_float("SIMILARITY_THRESHOLD", 0.6),
        search_top_k=_env_int("SEARCH_TOP_K", 5),
        neighbors_per_item=_env_int("NEIGHBORS_PER_ITEM", 3),
        cors_origins=tuple(
            o.strip()
            for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if o.strip()
        ),
        data_dir=data_dir,
        cache_dir=data_dir / "cache",
        vault_dir=data_dir / "vaults",
        runs_dir=data_dir / "runs",
        replays_dir=data_dir / "replays",
        prompts_dir=REPO_ROOT / "prompts",
    )
