# FocAI (repo: research-pruner): project brief for resume extraction

**Purpose of this file:** hand it to an AI agent so it can write accurate resume bullets for this
project. Everything below was read from the code and git history. Facts are separated from
judgement calls so the agent does not have to guess.

## Instructions for the agent reading this

1. Write 3 to 5 resume bullets (and, if asked, a one-line project title/summary and a skills list).
2. Use only facts from this file. Do **not** invent users, adoption, benchmark improvements,
   latency/cost savings, awards or placements. None are recorded here (see "What is NOT known").
3. Bullets should start with a strong past-tense verb, name the technology, and state the outcome
   or scale where a real number exists (section 6 lists the numbers that are safe to use).
4. The person's own role is in section 7. If it is still blank, ask the person which parts they
   built before attributing anything to them; this is a team hackathon project.
5. Offer a few variants by target role (backend / full-stack / AI-agents), since the project
   supports all three framings.

---

## 1. One-paragraph summary

FocAI is a **human-steered AI research agent with a personal knowledge vault**, built at the
hackathon **Hack the Valley 11** (git history: 2026-10-16 to 2026-10-18, 32 commits). An LLM agent
explores a problem as a **tree of hypotheses**; each node is a hypothesis, an experiment that tests
it, and a verdict. Weak branches are **pruned ("parked") before and after the experiment**, each
with a one-sentence reason, and are never deleted, so a human can restore them. "Relevant" is judged
against the user's **own vault** of papers, notes, questions and corrections, so the agent prefers
ideas that are relevant *and new to that person*. A person can steer the run live: keep, park or
restore nodes, type new instructions mid-run, answer the agent's questions, switch to manual mode,
pause or stop. The tree search with pre- and post-execution pruning is adapted from the ToolTree
paper (ICLR 2026, arXiv:2603.12740), applied to research hypotheses instead of tool calls.

## 2. The problem it addresses

Autonomous research agents burn compute on experiments that are not worth running, repeat what the
user already knows, and are opaque: users cannot see why a branch was dropped or intervene
cleanly. FocAI cuts wasted experiments with two-sided pruning, personalises "novelty" with a vault,
and makes every decision visible and reversible.

## 3. What it does (features)

**Two run types**
- *Code run* (user gives a folder/files plus a command): the agent proposes edits to the user's
  files, the system runs the user's command, reads the result JSON, and compares to a measured
  baseline. The best supported version is left applied and a patch is produced.
- *Research run* (no files): hypotheses are guesses at what the user wants to see; experiments
  search the vault (and optionally the web) and judge whether the resources found are relevant.

**Agent loop** (propose -> pre-score -> experiment -> synthesis + post-score -> next action)
- Proposes up to 3 hypotheses per step from *different families* (e.g. caching, batching) so
  exploration stays diverse.
- Pre-scorer (fast LLM) ranks sibling candidates on plausible / relevant / novel against the vault;
  low scorers are parked with a reason citing the deciding vault note.
- Post-scorer plus a synthesis agent judge the measured result and choose the next action from:
  more experiments, new hypothesis, diagnose, combine, resolve (contradicting note vs result),
  transfer, revert, or stop.
- Deterministic queue priority (weights on pre-score, lineage, steering relevance, novelty, depth)
  with family balancing so one family cannot starve the rest.
- Hard budgets enforced in code: depth 3, branching 3, 14 experiments, per-phase tool-call caps,
  edit-size limits, experiment timeout. A final report is written as a "conclusion" node.

**Human steering**
- Keep / park / restore / conclude any node; a human decision always overrides later re-rates.
- Mid-run instructions append objectives, abort and restart the current step, trigger a batched
  LLM re-rate of the whole tree, and produce ranked next-step suggestions.
- **Forks:** after objectives change, the system proposes restarting from the deepest node that
  still fits. A fork card shows the path, what would be parked, and nothing changes until a person
  confirms; **undo** restores the exact previous tree.
- Manual mode (the run waits for the person to pick which hypothesis to pursue), pause/resume/stop.

**Knowledge vault**
- Ingest notes, questions, corrections, or paper links (arXiv links are fetched and summarised).
- Each item is embedded (Gemini embeddings, 768-d); nearest neighbours are linked and an LLM labels
  each link *contradicts / supports / agrees / investigate* with a one-line reason.
- Items are laid out on an interactive **3D mind map** (PCA of embeddings; new items are placed
  beside their nearest neighbour so existing items never shuffle; users can drag cards).
- Standing "directives" ("prefer optimizer changes") are appended to every prompt.

**Observability**
- Every tool call by the agent must include a `reason` argument; it is logged per node, so each
  node has an auditable log of what the agent looked up and why.

## 4. Architecture and tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11+, FastAPI, pydantic v2, uvicorn, numpy, httpx, `uv` for packaging |
| LLM | Google Gemini via `google-genai` (a fast model for scoring/ingest, a stronger one for proposing; Gemini embeddings) |
| Frontend | React 19 (with React Compiler), TypeScript, Vite, Tailwind 4, zustand, `@xyflow/react` (run tree), `react-force-graph-3d` + three.js (3D vault map) |
| Realtime | Server-Sent Events (SSE) event stream with resume (`Last-Event-ID`) |
| Storage | Plain files on disk (JSON / JSONL): vaults, run events, snapshots, LLM cache |
| Testing | pytest + pytest-asyncio, ruff (backend); tsc + eslint (frontend) |

Structure: `backend/pruner/` has `api/` (FastAPI routers), `core/` (models, events, config, the LLM
wrapper), `runs/` (lifecycle, persistence, SSE), `orchestrator/` (the main loop and its phases),
`pruning/` (pre/post scorers), `agent/` (tool-calling loop and tools), `vault/`, and `workspace/`
(in-place file edits with versions). `prompts/` holds 19 prompt files loaded by name.
`docs/ARCHITECTURE.md` is a longer study guide.

## 5. Engineering highlights (the interesting decisions)

These are the strongest material for bullets; each is real and in the code.

1. **Pruning is a score plus a reason, never a delete.** Every park is restorable and cites the
   vault note that drove it; restoring files a "correction" back into the vault.
2. **Two-sided pruning (pre- and post-score)**, adapted from a published paper to a new domain.
   Pre-score saves experiments; post-score stops weak results from spawning children.
3. **The agent proposes; the orchestrator disposes.** The agent has no write or run tools. Proposed
   edits are validated in memory first (applies cleanly, syntax parses, no removed signatures,
   diff <= 40 lines, <= 6 edits in <= 3 files, not a repeat), with one batched repair call for
   failures. User files are touched only when a node actually runs, and are backed up and restored
   at the end.
4. **Experiment commands come from the human, verbatim.** A command is accepted only if it appears
   word for word in text the user wrote or attached; otherwise the run asks. No LLM-authored shell
   commands are executed.
5. **Policy in code, judgement in the LLM.** Queue priority, budgets, fork-point choice and
   keep/park thresholds are deterministic and unit-tested; the LLM supplies scores and text.
6. **Event-sourced UI.** Every event is persisted to disk before being published and carries the
   whole object, so reconnect, history, resume and replay all use the same mechanism.
7. **Resilience:** disk cache of every LLM call (keyed on the full request, including tool
   conversation) for deterministic reruns; per-role API keys with automatic failover to backup keys
   on HTTP 429; stop cancels in-flight LLM calls; runs saved as "running" are recovered paused
   after a server restart and resume without redoing finished stages; per-run path locks; a replay
   mode that streams a saved run with original timing and makes no LLM calls (the demo fallback).
8. **Structured LLM output with a corrective retry**, pydantic schemas as response schemas, and a
   two-stage approach where tools and JSON schema cannot be combined.
9. **Shared contract:** backend pydantic models mirrored in TypeScript types; frontend fixtures are
   generated from the real backend models and a test fails if they go stale.

## 6. Numbers that are safe to cite (verified from the repo)

| Fact | Value |
|---|---|
| Backend Python source | ~11,000 lines |
| Backend tests | 41 test files, ~7,200 lines, 397 test functions |
| Frontend TypeScript/TSX | ~9,100 lines |
| Prompt files | 19 |
| Server-sent event types | 20 |
| Commits / time span | 32 commits over about 3 days (2026-10-16 to 2026-10-18) |
| Default run limits | depth 3, branching 3, 14 experiments per run |
| Vault link settings | cosine similarity >= 0.7, up to 3 neighbours per item |
| Local run history | 11 saved runs in `data/runs` (development and demo runs; not user metrics) |

## 7. The person's role (fill this in before extracting bullets)

> The git history has a single author, but the project was built at a hackathon and may have had
> teammates. The repo does not say who built which part. Replace this block with the person's real
> contribution, for example: "I built X and Y; teammates built Z". The agent must not attribute
> work that is not listed here.

- Role / parts built by the person: _TODO_
- Team size: _TODO_
- Hackathon outcome (award, placement, demo audience), if any: _TODO_

## 8. What is NOT known (do not claim these)

- No benchmark showing how much compute the pruning saves versus an unpruned run, or whether the
  agent's answers are better. (The data model has an `unpruned` mode and token accounting for the
  scorer's cost, but no results are recorded in the repo.)
- No real users, deployment or production usage. It runs locally.
- No hackathon award or ranking is recorded in the repo.
- Model quality depends on free-tier Gemini quotas (the docs name this as the main risk).

## 9. Known limitations (useful for honest interview answers)

- The root README is stale (still says the agent and tree are not built); `docs/ARCHITECTURE.md`
  is current.
- Acting on a *finished* run (node actions, new instructions) is refused; not built yet.
- The experiment cache is off by default because files outside the editable set can change.

## 10. Example bullet shapes (style guide only; verify against sections 5 to 7 first)

- Built a human-steerable research agent (FastAPI, React 19, Gemini) that explores problems as a
  tree of hypotheses and prunes weak branches before and after each experiment, adapting the
  ToolTree bidirectional-pruning idea (ICLR 2026) to research.
- Designed a safety model where the agent can only *propose* edits: changes are validated in memory
  and applied by the orchestrator, user commands are accepted only if quoted verbatim, and files are
  backed up and restored, backed by 397 pytest tests.
- Implemented an event-sourced SSE pipeline (events persisted before publish, resumable by event
  id) giving live tree updates, pause/resume, crash recovery and offline replay from one mechanism.
- Built a personal knowledge vault with Gemini embeddings, LLM-labelled links
  (supports/contradicts/agrees/investigate) and an interactive 3D mind map (three.js), used to
  personalise which research ideas count as "novel".
- Added resilience for rate-limited LLM APIs: per-role keys with automatic failover on 429s, a disk
  cache for deterministic reruns, and cancellation of in-flight calls on stop.
