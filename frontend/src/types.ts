// Mirrors backend/pruner/core/models.py and backend/pruner/core/events.py. Keep in sync by hand;
// the fixtures in ./fixtures are generated from the backend models and validated in CI-style
// tests (backend/tests), so a drift shows up there first.

export type VaultKind =
  | 'paper'
  | 'note'
  | 'question'
  | 'correction'
  | 'learned'
  | 'directive'
export type VaultRelation = 'contradicts' | 'supports' | 'agrees' | 'investigate'
export type NodeType = 'hypothesis' | 'experiment' | 'reading' | 'conclusion' // conclusion: the run's answer
export type NodeStatus = 'pending' | 'running' | 'done' | 'parked' | 'failed'
export type Verdict = 'keep' | 'park'
export type DecisionStage = 'pre' | 'post' | 'human'
export type Decider = 'agent' | 'human'
export type RunMode = 'pruned' | 'unpruned'
export type RunStatus = 'running' | 'done' | 'failed'

// Backend PERSON_PATTERN: a person's name doubles as a filename, so no leading "_" (reserved).
export const PERSON_PATTERN = /^[a-z0-9][a-z0-9_-]{0,31}$/

// ---- vault

// A spot on the 3D vault map.
export interface Position {
  x: number
  y: number
  z: number
}

export interface VaultItemView {
  id: string
  person: string
  kind: VaultKind
  title: string
  summary: string
  tags: string[]
  source_text: string
  investigate: boolean
  // Set once a person has moved the card by hand (the Move tool). Always wins over auto_position,
  // and a card with a position is pinned there.
  position?: Position | null
  // The backend's automatic layout (similar items close together). Where to start cards that were
  // never moved.
  auto_position?: Position | null
  retrieval_count: number
  created_at: number
}

// Undirected; source is the newer item, target the older one.
export interface VaultEdge {
  source: string
  target: string
  weight: number
  relation: VaultRelation
  reason: string
}

export interface VaultGraph {
  nodes: VaultItemView[]
  edges: VaultEdge[]
}

// A person's standing instruction (e.g. "prefer optimizer changes"). Not a vault item: no
// embedding or links; kept in its own list and handed to the agent as-is.
export interface Directive {
  id: string
  person: string
  text: string
  created_at: number
}

// ---- scoring

// One point-form goal of the research, written from the spec when the run starts. Later
// instructions can append more; nothing is rewritten or removed.
export interface Objective {
  id: string // "o1", "o2", ...
  text: string
  source: string // "spec", or the id of the instruction that added it
}

export interface PreScore {
  plausible: number
  relevant: number
  novel: number
  overall: number
}

export interface Decision {
  verdict: Verdict
  stage: DecisionStage
  reason: string
  vault_items_used: string[]
}

export interface PersonScore {
  person: string
  verdict: Verdict
  score: number
  reason: string
  vault_items_used: string[]
}

export interface TokenUsage {
  agent: number
  scorer: number
  total: number
}

// ---- tree

// FLAG (ignore unless asked): backend class is `Node`; this name differs from the backend.
export interface TreeNode {
  id: string
  run_id: string
  parent_id: string | null
  depth: number
  type: NodeType
  description: string
  status: NodeStatus
  pre_score: PreScore | null
  post_score: number | null
  decision: Decision | null
  decided_by: Decider | null
  result: string | null
  criteria_progress: string[] // ids of the objectives this node advanced
  tokens: TokenUsage
  usefulness_count: number
  person_scores: Record<string, PersonScore>
  created_at: number
  // --- the orchestrator's fields (optional: older snapshots don't have them)
  family?: string | null
  // Where the node is in its cycle: proposed, its experiment running, being judged, finished.
  phase?: NodePhase
  summary?: string // one line about this node (used in later prompts)
  hypothesis?: HypothesisSpec | null // the whole proposal (description is only its short title)
  edit?: Edit | null
  base_version?: string | null
  version?: string | null
  combines?: string[] // other nodes merged in (combine); for the conclusion, every judged node
  experiment?: ExperimentRun | null
  synthesis?: Synthesis | null
  verdict?: HypothesisVerdict | null
  pre_band?: PreBand | null // how to show the pre-score
  closed?: boolean // the agent chose "stop" here: no more children
  priority?: number | null
  // The latest steering re-rate: how relevant this node is to what's asked now (0..1), and why.
  directive_score?: number | null
  directive_reason?: string
  needs_remeasure?: boolean
  missing_metrics?: string[]
  // A person's keep/park/restore on a running node, applied once its step has finished.
  pending_action?: HumanAction | null
  // Manual mode: this node's proposals are ready and the run waits for a person to choose which to
  // pursue (keep one to run it next, park the ones to drop). Shown with a yellow ring.
  awaiting_choice?: boolean
  // A revert option: go back to this earlier node's code (the step since went the wrong way) and try
  // something else from there. No experiment runs for it. Shown as "Revert to <id>".
  revert_to?: string | null
  tool_calls?: Record<string, number> // calls used, per phase
}

export type NodePhase = 'hypothesis' | 'experiment' | 'synthesis' | 'complete'
export type HypothesisVerdict = 'supported' | 'refuted' | 'inconclusive'
export type PreBand = 'low' | 'medium' | 'high'
export type HumanAction = 'keep' | 'park' | 'restore'
export type NextAction = 'more_experiments' | 'new_hypothesis' | 'diagnose' | 'combine' | 'resolve' | 'transfer' | 'revert' | 'stop'
// How a step moved things compared with the previous round.
export type Direction = 'better' | 'worse' | 'same' | 'unclear'

export interface HypothesisSpec {
  statement: string
  rationale: string
  family: string
  planned_experiment: string
  expected_signal: string
  measures: string[]
  queries: string[] // research runs: the searches its experiment runs
}

export interface Edit {
  edits: { path: string; find: string; replace: string; replace_all: boolean }[]
  new_files: { path: string; content: string }[]
  stats: { files: number; added: number; removed: number } | null
}

export interface ExperimentRun {
  command: string
  exit_code: number | null
  timed_out: boolean
  duration_s: number
  stdout_tail: string
  stderr_tail: string
  result: Record<string, unknown> | null
  metrics: Record<string, number>
  error: string | null
  cached: boolean
}

export interface Synthesis {
  measured: string
  explanation: string
  verdict: HypothesisVerdict
  confidence: number
  finding: string
  direction?: Direction // vs the previous round: was this step the right way?
  next_action: NextAction
  next_reason: string
  action_targets: string[]
  action_brief: string
}

export interface Caps {
  max_depth: number
  branching: number
  node_budget: number
  tool_calls_per_phase?: number
}

export interface RunTotals {
  tokens: TokenUsage
  nodes_total: number
  nodes_parked: number
  nodes_restored: number
  experiments_run?: number
  elapsed_s: number
}

export type InstructionKind = 'spec' | 'steer'

export interface Instruction {
  id: string
  kind: InstructionKind
  text: string
  // Steering instructions show as chips that can be turned off (PATCH .../instructions/{id}); an
  // inactive one is left out of every prompt. The spec is always active.
  active?: boolean
  created_at: number
}

export interface Run {
  id: string
  question: string
  objectives: Objective[]
  instructions: Instruction[] // spec first, then steering
  directives: string[] // directive texts last sent for this run, appended to every prompt
  people: string[]
  primary_person: string // whose vault drives pruning
  vault_people: string[] // whose vaults the scorers search
  mode: RunMode
  status: RunStatus
  // Why a finished run ended: "stopped" (the user), "limit" (a cap reached), "error" (a real
  // failure, with the message in `error`). Older runs don't have it.
  end_reason?: 'stopped' | 'limit' | 'error'
  error?: string
  // True while the run is paused: its agent takes no further step until resumed. Not a status (the
  // run is still "running"); cleared when the run ends or is stopped.
  paused: boolean
  caps: Caps
  paths?: string[] // the user's files or folders (server paths)
  // The run waits for a person: to answer the command question, or (manual mode) to choose which
  // proposed hypothesis to pursue next.
  // "fork": a fork is suggested and nothing new runs until a person confirms or dismisses it (fork_id).
  awaiting?: 'command' | 'choice' | 'fork' | null
  fork_id?: string | null
  // Manual mode (POST /runs/{id}/manual): before each experiment the run waits for a person's choice.
  manual?: boolean
  best_node_id?: string | null // the node whose code is left applied at the end
  patch_ready?: boolean // GET /runs/{id}/patch has the final changes
  final_answer: string | null
  totals: RunTotals
  created_at: number
}

export interface DeadEnd {
  id: string
  run_id: string
  node_id: string
  description: string
  reason: string
}

// A question the run asks: the experiment command when none was given ("command"), or a
// targeted one ("clarify"). GET /runs/{id}/questions; POST .../questions/{qid}/answer.
export interface Question {
  id: string
  run_id: string
  node_id: string | null
  person: string
  text: string
  purpose?: 'command' | 'clarify'
  status: 'pending' | 'answered'
  answer: string | null
  created_at: number
}

// One line in the run's shared findings log.
export interface Finding {
  id: string
  run_id: string
  node_id: string | null
  family: string | null
  verdict: HypothesisVerdict
  text: string
  evidence_node_ids: string[]
  metrics: Record<string, number>
  source: 'orchestrator' | 'agent_tool'
  reason: string
  created_at: number
}

// Where the run could continue from, offered after a steering re-rate or a fork request.
// GET /runs/{id}/suggestions; POST .../suggestions/{sid}/confirm | dismiss.
export interface Suggestion {
  id: string
  run_id: string
  node_id: string
  action: 'run' | 'expand' | 'restore' | 'remeasure' | 'fork'
  reason: string
  family: string | null
  score: number
  source: 'steer' | 'fork'
  instruction_id: string | null
  fork_id?: string | null // action "fork": the fork it confirms or dismisses
  status: 'open' | 'confirmed' | 'dismissed' | 'replaced'
  created_at: number
}

export interface RunSnapshot {
  run: Run
  nodes: TreeNode[]
  dead_ends: DeadEnd[]
  questions: Question[]
  findings?: Finding[]
  suggestions?: Suggestion[]
}

// ---- API requests

export interface StartRunRequest {
  question: string
  spec?: string
  mode?: RunMode
  primary_person: string
  people?: string[] | null
  // Whose vaults the scorers search; defaults to [primary_person], [] = no vault.
  vault_people?: string[] | null
  // Directive texts (not ids), appended to the prompts as-is.
  directives?: string[]
  // Absolute paths of files (or folders) on the backend's machine the run works on; the backend
  // rejects relative or missing ones (422). They are edited in place.
  paths?: string[]
  manual?: boolean // start in manual mode
}

export interface InstructionRequest {
  text: string
  // The full list of active directive texts, replacing the run's previous list. Omit to keep it.
  directives?: string[] | null
}

export interface IngestRequest {
  person: string
  kind?: Exclude<VaultKind, 'directive'> // directives use DirectiveRequest instead
  text: string
  title?: string | null
  tags?: string[] // topic tags (normalized to lowercase-hyphenated, at most 5)
}

// POST /api/vault/vaults: create an empty vault so the person shows up before any item exists.
// 201 -> VaultSummary; 409 if that person already has a vault.
export interface CreateVaultRequest {
  person: string
}

export interface VaultSummary {
  person: string
  item_count: number
}

// POST /api/vault/layout/regenerate -> VaultGraph. Recomputes every automatic position; manual
// moves are kept unless reset_moved is true.
export interface RegenerateLayoutRequest {
  reset_moved?: boolean
}

// POST /api/vault/directives -> Directive
export interface DirectiveRequest {
  person: string
  text: string
}

export interface IngestResult {
  item: VaultItemView
  edges: VaultEdge[]
}

// ---- SSE events (the `type` field is also the SSE event name)

interface EventBase {
  seq: number
  run_id: string
  ts: number
}

// awaiting: the node's awaiting_choice flag flipped (either way).
export type NodeChange = 'running' | 'scored' | 'done' | 'parked' | 'kept' | 'restored' | 'failed' | 'awaiting'

export type PrunerEvent =
  | (EventBase & { type: 'run_started'; run: Run })
  // The run's objectives in full: when first written, and again whenever an instruction adds more.
  | (EventBase & { type: 'objectives_updated'; objectives: Objective[] })
  | (EventBase & { type: 'node_created'; node: TreeNode })
  | (EventBase & { type: 'node_updated'; node: TreeNode; change: NodeChange })
  | (EventBase & { type: 'instruction_added'; instruction: Instruction })
  | (EventBase & {
      type: 'vault_retrieved'
      node_id: string | null
      person: string
      query: string
      item_ids: string[]
      similarities: number[]
    })
  | (EventBase & { type: 'vault_item_added'; item: VaultItemView; edges: VaultEdge[] })
  | (EventBase & { type: 'activity'; message: string; node_id: string | null })
  | (EventBase & { type: 'question_asked'; question: Question })
  | (EventBase & { type: 'question_answered'; question: Question })
  // Run-level state changed (awaiting an answer, instructions toggled...): the whole run.
  | (EventBase & { type: 'run_updated'; run: Run })
  | (EventBase & { type: 'node_log'; node_id: string; entry: LogEntry })
  | (EventBase & { type: 'finding_added'; finding: Finding })
  | (EventBase & { type: 'idea_added'; idea: RunIdea })
  // A new open set; `replaced` are the ids of the earlier open ones.
  | (EventBase & { type: 'suggestions_ready'; suggestions: Suggestion[]; replaced: string[] })
  | (EventBase & { type: 'suggestion_resolved'; suggestion: Suggestion })
  // A node no longer exists (undoing a fork deletes the nodes created after it).
  | (EventBase & { type: 'node_removed'; node_id: string })
  | (EventBase & { type: 'fork_updated'; fork: ForkRequest })
  | (EventBase & { type: 'run_completed'; run: Run })
  | (EventBase & { type: 'run_failed'; error: string })

// ---- other finished routes

// One node on a fork card: where it is and how relevant it is to the amended objectives.
export interface ForkStep {
  node_id: string
  description: string
  depth: number
  score: number | null // the steering re-rate's relevance, 0..1 (shown as 0..10)
}

// GET /api/runs/{id}/forks: after the objectives are amended, the amend agent suggests restarting
// from the node F (node_id) the new objectives still fit. Nothing changes until a person confirms:
// then every live node off the root-to-F path (and F's descendants) is parked, new hypotheses grow
// from F, and undo restores the tree as it was (see FORK_PLAN.md). Older requests have only the
// first fields.
export interface ForkRequest {
  id: string
  run_id: string
  node_id: string // F
  reason: string
  objective_ids: string[]
  status: 'requested' | 'confirmed' | 'dismissed' | 'replaced' | 'undone'
  path?: ForkStep[] // root .. F, with scores
  below?: ForkStep[] // deeper choices for F
  park_ids?: string[] // parked on confirm
  kept_overridden?: number // how many of them a person had kept (the keep is cleared)
  flagged_ids?: string[] // off-path but relevant: "park anyway", untickable
  web_search?: boolean // the new hypotheses can search the web (a provider is set up)
  suggestion_id?: string | null
  confirmed_at_node?: string | null // where it was confirmed (a person may move F)
  created_at: number
}

// POST /api/runs/{id}/pause and /resume -> 202. Calls in flight finish; the next step waits (pause)
// or goes ahead (resume). 404 unknown run, 409 already finished; pausing a paused run is fine.
export interface PauseResult {
  run_id: string
  paused: boolean
}

// POST /api/runs/{id}/stop -> 202 (404 unknown run, 409 already finished).
export interface StopResult {
  run_id: string
  cancelled_calls: number
}

// GET /api/prompts and /api/prompts/{name}: the templates sent to the LLM (read-only).
export interface PromptInfo {
  name: string
  text: string
  placeholders: string[]
}

// GET /api/config: what the UI may show. Scores are on the 1 to 10 scale.
export interface PublicConfig {
  fast_model: string
  strong_model: string
  agent_hypothesis_model?: string
  agent_synthesis_model?: string
  tool_calls_per_phase?: number
  write_tool_calls_per_phase?: number
  branch_finding_min_confidence?: number
  experiment_timeout_s?: number
  experiment_cache?: boolean
  vault_model: string
  embedding_model: string
  max_depth: number
  branching: number
  node_budget: number
  pre_score_min: number
  run_score_min: number
  post_score_min: number
  rescore_park_below: number
  backtrack_below: number
}

// ---- per-run vault (GET | POST /api/runs/{id}/vault)

// One thing the agent came up with or found while exploring, filed under the branch (tree path) it
// came from. Not a vault item: no owner, no embedding, no links. `branch_finding`: a whole-branch
// conclusion the agent wrote once it was fairly sure.
export interface RunIdea {
  id: string
  branch: string
  title: string
  summary: string
  kind?: 'idea' | 'branch_finding'
  confidence?: number | null
  node_ids?: string[]
  created_at?: number
}

// The agent's own discoveries for one run. Stored on disk with the run, e.g.
// data/runs/<run_id>/vault.json.
export interface RunVault {
  run_id: string
  ideas: RunIdea[]
}

// ---- node logs (GET /api/runs/{id}/nodes/{node_id}/logs; live as node_log events)

// One entry in a node's log: a reasoning step, a tool call or its result, a scoring decision...
export type LogKind = 'thought' | 'tool_call' | 'tool_result' | 'decision' | 'activity' | 'error'

export interface LogEntry {
  id: string
  ts: number
  kind: LogKind
  title: string // one line: "Searched the vault", "Pre-score 7.2 / 10", ...
  text: string // the detail: the reasoning, the tool's result, the reason for a decision
  tool?: string | null // tool_call / tool_result only
  args?: Record<string, unknown> | null // tool_call only
  phase?: string | null
}
