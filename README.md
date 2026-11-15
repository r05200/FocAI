# FocAI

A human-steered research agent with a personal knowledge vault, built for Hack the Valley 11.
Agents explore, humans steer, and the tree shows everyone what is happening and why.

An LLM agent explores a problem as a **tree of hypotheses**. Each node is a hypothesis, the
experiment that tests it, and a verdict. A **pre-score** judges whether an experiment is worth
running; a **post-score** judges its result. Weak branches are **parked** (pruned) with a one-line
reason, and a person can restore them at any time. "Relevant" is judged against the person's own
vault, so the agent favors ideas that are relevant _and new to this person_.

## Features

- **Run tab:** a live tree of the agent's work. Keep, park, restore or conclude any node, answer
  the agent's questions, type new instructions mid-run (objectives are amended, the tree is
  re-rated, and a fork can be suggested, confirmed or undone), switch to manual mode, pause, resume
  or stop. Each node has a log of the agent's tool calls with the reason for each.
- **Vault tab:** a 3D mind map of what a person has read, noted or asked. New items are embedded,
  linked to their nearest neighbors and labelled contradicts / supports / agrees / investigate.
  Standing directives ("prefer optimizer changes") are added to every prompt.
- **History tab:** past runs, reopened from their saved events.
- **Settings tab:** the backend's public configuration.
- **Two kinds of run:**
  - _Code run_ (you give a folder or files, and a command in your prompt): the agent proposes small
    edits, the orchestrator validates and applies them in place, runs your command, and compares the
    result JSON to a baseline. The best supported version is left applied and a patch is saved.
  - _Research run_ (no files): hypotheses are guesses at what you want to see, and experiments
    search your vault (and the web, if a search provider is set up).

The agent only proposes; the orchestrator validates, applies and runs. The experiment command is
only accepted if it appears word for word in text you wrote. Files are backed up first and settled
at the end, even on stop or failure.

For the full picture, read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Layout

```
backend/    FastAPI + pydantic (uv). pruner/core/models.py and events.py are the contract.
frontend/   Vite + React 19 + TypeScript. src/types.ts mirrors the backend models.
prompts/    One file per LLM prompt, loaded by name (see prompts/README.md).
docs/       ARCHITECTURE.md: how it works, design decisions, thresholds, demo notes.
data/       Local state, all git-ignored: vaults, run events and snapshots, LLM cache, work backups.
```

## Setup

```sh
cp .env.example .env            # add GEMINI_API_KEY_AGENT and GEMINI_API_KEY_SUPPORTING
cd backend && uv sync
cd ../frontend && npm install
```

Two keys keep the agent and everything else (vault, scorers, objectives) on separate quotas.
`.env.example` lists the optional overrides: a fork-agent key, backup keys (`_2`, `_3`) that are
used when a key hits a rate limit, model names, thresholds and run caps (all `PRUNER_*`).

Optional web search for research runs and the agent: set `PRUNER_SEARCH_PROVIDER=exa` and
`SEARCH_API_KEY`.

## Run

```sh
cd backend && uv run uvicorn pruner.api.app:app --reload --port 8000   # API docs at /docs
cd frontend && npm run dev                                             # http://localhost:5173
```

The dev server proxies `/api` to port 8000. `data/` starts empty on a fresh clone: create a vault
in the Vault tab and add a few notes or paper links before starting a run, so pruning has something
to judge against. If the backend is unreachable the UI falls back to the fixtures below.

Try a vault ingest from the command line (needs `GEMINI_API_KEY_SUPPORTING`):

```sh
curl -s localhost:8000/api/vault/items -H 'content-type: application/json' \
  -d '{"person": "alice", "kind": "note", "text": "4-bit KV cache quantization hurt recall past 32k"}'
```

## Checks

```sh
cd backend && uv run pytest && uv run ruff check .
cd frontend && npx tsc -b && npm run lint
```

## Fixtures

The frontend can build against fake data in `frontend/src/fixtures/`, generated from the real
backend models so it cannot drift from the contract:

```sh
cd backend && uv run python -m pruner.fixtures
```

`tests/test_fixtures.py` fails if the committed JSON is stale. All fixture content is placeholder
(titles are prefixed `[fixture]`).

## Replays

A saved run can be streamed back with its original timing, with no LLM calls. This is the demo
fallback when the network or API quota fails:

```sh
cd backend && uv run python -m pruner.replay export <run_id> <name>
# then GET /api/replays/<name>/events
```

## Inspiration

The tree search with pruning on both sides of an experiment (a pre-score before it runs, a
post-score after) is inspired by ToolTree:

> Shuo Yang, Soyeon Caren Han, Yihao Ding, Shuhe Wang and Eduard Hovy. _ToolTree: Efficient LLM
> Agent Tool Planning via Dual-Feedback Monte Carlo Tree Search and Bidirectional Pruning._
> ICLR 2026. [arXiv:2603.12740](https://arxiv.org/abs/2603.12740)

ToolTree plans an LLM agent's tool use with an MCTS-style search, guiding it with pre-execution
priors and post-execution rewards and pruning weak branches before and after a tool runs. This
project applies that idea to research hypotheses instead of tool calls.
