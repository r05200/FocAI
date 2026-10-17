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
export type NodeType = 'hypothesis' | 'experiment' | 'reading'
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
}

export interface Caps {
  max_depth: number
  branching: number
  node_budget: number
}

export interface RunTotals {
  tokens: TokenUsage
  nodes_total: number
  nodes_parked: number
  nodes_restored: number
  elapsed_s: number
}

export type InstructionKind = 'spec' | 'steer'

export interface Instruction {
  id: string
  kind: InstructionKind
  text: string
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
  caps: Caps
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

export interface Question {
  id: string
  run_id: string
  node_id: string
  person: string
  text: string
  status: 'pending' | 'answered'
  answer: string | null
  created_at: number
}

export interface RunSnapshot {
  run: Run
  nodes: TreeNode[]
  dead_ends: DeadEnd[]
  questions: Question[]
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

// PATCH /api/vault/items/{id}/position -> 204. The Move tool: where a card now sits.
export type MoveItemRequest = Position

// PATCH /api/vault/positions -> 204: several moves at once; an unknown id rejects all (404).
export interface MoveItemsRequest {
  positions: (Position & { id: string })[]
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

export interface AnswerRequest {
  answer: string
}

// ---- SSE events (the `type` field is also the SSE event name)

interface EventBase {
  seq: number
  run_id: string
  ts: number
}

export type NodeChange = 'running' | 'scored' | 'done' | 'parked' | 'kept' | 'restored' | 'failed'

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
  | (EventBase & { type: 'run_completed'; run: Run })
  | (EventBase & { type: 'run_failed'; error: string })

// ---- other finished routes

// GET /api/runs/{id}/forks: where the amend agent asked to restart exploration (not built yet).
export interface ForkRequest {
  id: string
  run_id: string
  node_id: string
  reason: string
  objective_ids: string[]
  status: 'requested'
  created_at: number
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
