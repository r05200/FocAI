"""Single place for model names, thresholds, caps and paths.

Everything is overridable with a PRUNER_* environment variable (or a .env file at the repo
root), so tuning during the hackathon never means editing code.

Gemini defaults were probed with real calls on 2026-10-17. The 2.5 models are listed but refuse
new users (404), and the Pro models had no quota on this key (429), so "strong" is 3.5 Flash.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]

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
    embedding_dim: int  # Gemini embeddings are truncated to this many dimensions
    vault_model: str  # dedicated to vault ingestion and relation labelling
    temperature: float

    # --- Agent caps (PRD: depth ~4, branching ~3, ~25 nodes) ---
    max_depth: int
    branching: int
    node_budget: int

    # --- Scoring thresholds (all 0..1, to be tuned on the demo question) ---
    # All scoring thresholds are on the judges' 1 to 10 scale.
    pre_score_min: float  # candidates with an overall score below this are parked
    run_score_min: float  # at or above this a candidate runs; between the two is borderline
    post_score_min: float  # results scoring below this (and advancing no objective) are parked
    rescore_park_below: float  # after an amended question, only scores below this stay parked

    # --- Vault ---
    similarity_threshold: float  # below this, vault search returns nothing
    search_top_k: int
    neighbors_per_item: int  # max edges created when an item is ingested
    # Min cosine similarity for an ingest-time edge. Arbitrary for now; gemini-embedding-001 at
    # 768 dims gave ~0.93-0.96 for related items and ~0.70 for an off-topic one.
    link_threshold: float

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
        fast_model=_env("FAST_MODEL", "gemini-3.5-flash-lite"),
        strong_model=_env("STRONG_MODEL", "gemini-3.5-flash"),
        embedding_model=_env("EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_dim=_env_int("EMBEDDING_DIM", 768),
        vault_model=_env("VAULT_MODEL", "gemini-3.5-flash-lite"),
        temperature=_env_float("TEMPERATURE", 0.1),
        max_depth=_env_int("MAX_DEPTH", 4),
        branching=_env_int("BRANCHING", 3),
        node_budget=_env_int("NODE_BUDGET", 25),
        pre_score_min=_env_float("PRE_SCORE_MIN", 2.0),
        run_score_min=_env_float("RUN_SCORE_MIN", 6.0),
        post_score_min=_env_float("POST_SCORE_MIN", 4.0),
        rescore_park_below=_env_float("RESCORE_PARK_BELOW", 4.0),
        similarity_threshold=_env_float("SIMILARITY_THRESHOLD", 0.6),
        search_top_k=_env_int("SEARCH_TOP_K", 5),
        neighbors_per_item=_env_int("NEIGHBORS_PER_ITEM", 3),
        link_threshold=_env_float("LINK_THRESHOLD", 0.8),
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
