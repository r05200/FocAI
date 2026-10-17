"""Single place for model names, thresholds, caps and paths.

Everything is overridable with a PRUNER_* environment variable (or a .env file at the repo
root), so tuning during the hackathon never means editing code.

Gemini defaults were probed with real calls on 2026-10-17. The 2.5 models are listed but refuse
new users (404), and the Pro models had no quota on this key (429), so "strong" is 3.5 Flash.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    # Two keys, so the agent and the supporting calls (vault, scorers, objectives) have separate
    # quotas. Hidden from repr so a printed Config never shows them.
    gemini_api_key_agent: str = field(repr=False)
    gemini_api_key_supporting: str = field(repr=False)
    fast_model: str  # scoring and ingestion
    strong_model: str  # planning and synthesis
    embedding_model: str
    embedding_dim: int  # Gemini embeddings are truncated to this many dimensions
    vault_model: str  # dedicated to vault ingestion and relation labelling
    temperature: float

    # --- Agent caps (depth ~3, branching ~3, ~12-15 experiments) ---
    max_depth: int
    branching: int
    node_budget: int  # the most experiments one run may run, the baseline included

    # --- The orchestrator's agent ---
    agent_hypothesis_model: str  # proposing hypotheses and edits (a bad edit wastes an experiment)
    agent_synthesis_model: str  # verdicts, findings and the next action
    # Whether the final JSON schema is sent together with the tools ("off" = tool turns first,
    # then a separate structured call; "on" = both in one; "auto" = try "on", fall back to "off").
    agent_schema_with_tools: str
    tool_calls_per_phase: int  # read tools (vault, results, files, web) per phase
    write_tool_calls_per_phase: int  # each write tool (findings log, run vault) per phase
    branch_finding_min_confidence: float  # 0..1; below this write_findings_vault is refused
    agent_linked_cap: int  # notes reached only through a link that search_vault returns
    llm_min_interval_s: float  # least time between two API calls on one key (free-tier pacing)

    # --- Workspace and experiments (the user's files are edited in place) ---
    work_dir: Path  # backups, versions and logs of each run (never the user's files)
    experiment_timeout_s: float
    experiment_output_cap: int  # bytes of stdout and of stderr kept (the tail)
    code_context_chars: int  # how much file text goes into a prompt
    # A proposed edit is refused when it is bigger than this (keeps experiments small and focused).
    max_diff_lines: int  # added + removed lines
    max_edit_files: int
    max_edits: int  # search/replace edits plus new files

    # --- Scoring thresholds (on the judges' 1 to 10 scale; tune on the demo question) ---
    pre_score_min: float  # candidates with an overall score below this are parked
    run_score_min: float  # at or above this a candidate runs; between the two is borderline
    post_score_min: float  # results scoring below this (and advancing no objective) are parked
    rescore_park_below: float  # after an amended question, only scores below this stay parked
    # Amend agent: a branch counts as "low" below this. It backtracks to a node only when every
    # live branch under it is low, so keep it loose (low) to avoid redoing progress.
    backtrack_below: float

    # --- Vault ---
    similarity_threshold: float  # below this, vault search returns nothing
    search_top_k: int
    # The agent's search_vault tool: the closest agent_search_top notes that are at least
    # agent_search_threshold similar to the query (cosine of gemini-embedding-001 at 768 dims:
    # ~0.93-0.96 for related items, ~0.70 off-topic). Their "contradicts" and "investigate" links
    # come along (every one of them; the ingest link_threshold already keeps links close).
    agent_search_threshold: float
    agent_search_top: int
    neighbors_per_item: int  # max edges created when an item is ingested
    # Min cosine similarity for an ingest-time edge. gemini-embedding-001 at 768 dims gave
    # ~0.93-0.96 for related items and ~0.70 for an off-topic one, so 0.7 links loosely related
    # notes too; the vault LLM then drops pairs it judges "unrelated".
    link_threshold: float

    # --- Agent tools (all read-only) ---
    search_provider: str  # the web search API; "" = not set up yet (see pruner/agent/web.py)
    search_api_key: str = field(repr=False)
    fetch_timeout_s: float
    fetch_max_chars: int  # page text is cut to this length

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
        gemini_api_key_agent=os.environ.get("GEMINI_API_KEY_AGENT", ""),
        gemini_api_key_supporting=os.environ.get("GEMINI_API_KEY_SUPPORTING", ""),
        fast_model=_env("FAST_MODEL", "gemini-3.5-flash-lite"),
        strong_model=_env("STRONG_MODEL", "gemini-3.5-flash"),
        embedding_model=_env("EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_dim=_env_int("EMBEDDING_DIM", 768),
        vault_model=_env("VAULT_MODEL", "gemini-3.5-flash-lite"),
        temperature=_env_float("TEMPERATURE", 0.1),
        max_depth=_env_int("MAX_DEPTH", 3),
        branching=_env_int("BRANCHING", 3),
        node_budget=_env_int("NODE_BUDGET", 14),
        agent_hypothesis_model=_env("AGENT_HYPOTHESIS_MODEL", _env("STRONG_MODEL",
                                                                   "gemini-3.5-flash")),
        agent_synthesis_model=_env("AGENT_SYNTHESIS_MODEL", _env("FAST_MODEL",
                                                                 "gemini-3.5-flash-lite")),
        agent_schema_with_tools=_env("AGENT_SCHEMA_WITH_TOOLS", "off"),
        tool_calls_per_phase=_env_int("TOOL_CALLS_PER_PHASE", 3),
        write_tool_calls_per_phase=_env_int("WRITE_TOOL_CALLS_PER_PHASE", 1),
        branch_finding_min_confidence=_env_float("BRANCH_FINDING_MIN_CONFIDENCE", 0.7),
        agent_linked_cap=_env_int("AGENT_LINKED_CAP", 2),
        llm_min_interval_s=_env_float("LLM_MIN_INTERVAL_S", 0.0),
        work_dir=Path(_env("WORK_DIR", str(data_dir / "work"))),
        experiment_timeout_s=_env_float("EXPERIMENT_TIMEOUT_S", 600.0),
        experiment_output_cap=_env_int("EXPERIMENT_OUTPUT_CAP", 20_000),
        code_context_chars=_env_int("CODE_CONTEXT_CHARS", 16_000),
        max_diff_lines=_env_int("MAX_DIFF_LINES", 40),
        max_edit_files=_env_int("MAX_EDIT_FILES", 3),
        max_edits=_env_int("MAX_EDITS", 6),
        pre_score_min=_env_float("PRE_SCORE_MIN", 2.0),
        run_score_min=_env_float("RUN_SCORE_MIN", 6.0),
        post_score_min=_env_float("POST_SCORE_MIN", 4.0),
        rescore_park_below=_env_float("RESCORE_PARK_BELOW", 4.0),
        backtrack_below=_env_float("BACKTRACK_BELOW", 3.0),
        similarity_threshold=_env_float("SIMILARITY_THRESHOLD", 0.6),
        search_top_k=_env_int("SEARCH_TOP_K", 5),
        agent_search_threshold=_env_float("AGENT_SEARCH_THRESHOLD", 0.85),
        agent_search_top=_env_int("AGENT_SEARCH_TOP", 2),
        neighbors_per_item=_env_int("NEIGHBORS_PER_ITEM", 3),
        link_threshold=_env_float("LINK_THRESHOLD", 0.7),
        search_provider=_env("SEARCH_PROVIDER", ""),
        search_api_key=os.environ.get("SEARCH_API_KEY", ""),
        fetch_timeout_s=_env_float("FETCH_TIMEOUT_S", 15.0),
        fetch_max_chars=_env_int("FETCH_MAX_CHARS", 20_000),
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
