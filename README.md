# FocAI

A human-steered research agent with a knowledge vault, built for Hack the Valley 11.
Agents explore, humans steer, and the tree shows everyone what is happening and why.

- **Run tab:** a live tree of the agent's work. Branches are scored against the person's own
  vault, then kept or parked with a reason. Humans can keep, park, restore and answer questions.
- **Vault tab:** a mind map of what a person has read, noted or asked. The agent searches it, so
  "relevant" means relevant _and new to this person_.

**Status:** the vault backend works end to end (ingest with LLM title/blurb/tags, embeddings,
similarity links labelled contradicts / supports / agrees / investigate / unrelated). The agent, tree and UI
are not built yet.

## Layout

```
backend/    FastAPI + pydantic (uv). pruner/core/models.py and events.py are the contract.
frontend/   Vite + React + TypeScript. src/types.ts mirrors the backend models.
prompts/    One file per prompt (added as each step is built).
data/       Vaults and replays (committed); LLM cache and run state (git-ignored).
```

## Setup

```sh
cp .env.example .env            # add GEMINI_API_KEY_SUPPORTING (and _AGENT)
cd backend && uv sync
cd ../frontend && npm install
```

## Run

```sh
cd backend && uv run uvicorn pruner.api.app:app --reload --port 8000   # docs at /docs
cd frontend && npm run dev
```

All routes under `/api` are declared with their request and response models. Live so far:
`/api/health` and the `/api/vault/*` routes; the rest return `501` until built.

Try an ingest (needs `GEMINI_API_KEY_SUPPORTING` in `.env`):

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

The frontend builds against fake data in `frontend/src/fixtures/`, generated from the real
backend models so it cannot drift from the contract:

```sh
cd backend && uv run python -m pruner.fixtures
```

`tests/test_fixtures.py` fails if the committed JSON is stale. All fixture content is placeholder
(titles are prefixed `[fixture]`), not the demo corpus.

## Inspiration

The tree search with pruning on both sides of an experiment (a pre-score before it runs, a
post-score after) is inspired by ToolTree:

> Shuo Yang, Soyeon Caren Han, Yihao Ding, Shuhe Wang and Eduard Hovy. _ToolTree: Efficient LLM
> Agent Tool Planning via Dual-Feedback Monte Carlo Tree Search and Bidirectional Pruning._
> ICLR 2026. [arXiv:2603.12740](https://arxiv.org/abs/2603.12740)

ToolTree plans an LLM agent's tool use with an MCTS-style search, guiding it with pre-execution
priors and post-execution rewards and pruning weak branches before and after a tool runs. This
project applies that idea to research hypotheses instead of tool calls.
