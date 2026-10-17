// Mirrors backend/pruner/models.py and backend/pruner/events.py. Keep in sync by hand;
// the fixtures in ./fixtures are generated from the backend models and validated in CI-style
// tests (backend/tests), so a drift shows up there first.

export type VaultKind = 'paper' | 'note' | 'question' | 'correction' | 'learned'
export type NodeType = 'hypothesis' | 'experiment' | 'reading'
export type NodeStatus = 'pending' | 'running' | 'done' | 'pruned' | 'failed'
export type Verdict = 'keep' | 'prune'
export type DecisionStage = 'pre' | 'post' | 'human'
export type Decider = 'agent' | 'human'
export type RunMode = 'pruned' | 'unpruned'
export type RunStatus = 'running' | 'done' | 'failed'

// ---- vault

export interface VaultItemView {
  id: string
  person: string
  kind: VaultKind
  title: string
  summary: string
  tags: string[]
  source_text: string
  retrieval_count: number
  created_at: number
}

export interface VaultEdge {
  source: string
  target: string
  weight: number
}

export interface VaultGraph {
  nodes: VaultItemView[]
  edges: VaultEdge[]
}

// ---- scoring

export interface Criterion {
  id: string
  text: string
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
  criteria_progress: string[]
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
  nodes_pruned: number
  nodes_restored: number
  elapsed_s: number
}

export interface Run {
  id: string
  question: string
  checklist: Criterion[]
  people: string[]
  primary_person: string
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
  mode?: RunMode
  primary_person: string
  people?: string[] | null
}

export interface IngestRequest {
  person: string
  kind?: VaultKind
  text: string
  title?: string | null
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

export type NodeChange = 'running' | 'scored' | 'done' | 'pruned' | 'kept' | 'restored' | 'failed'

export type PrunerEvent =
  | (EventBase & { type: 'run_started'; run: Run })
  | (EventBase & { type: 'checklist_ready'; checklist: Criterion[] })
  | (EventBase & { type: 'node_created'; node: TreeNode })
  | (EventBase & { type: 'node_updated'; node: TreeNode; change: NodeChange })
  | (EventBase & {
      type: 'vault_retrieved'
      node_id: string | null
      person: string
      query: string
      item_ids: string[]
      similarities: number[]
    })
  | (EventBase & { type: 'vault_item_added'; item: VaultItemView; neighbor_ids: string[] })
  | (EventBase & { type: 'activity'; message: string; node_id: string | null })
  | (EventBase & { type: 'question_asked'; question: Question })
  | (EventBase & { type: 'question_answered'; question: Question })
  | (EventBase & { type: 'run_completed'; run: Run })
  | (EventBase & { type: 'run_failed'; error: string })
