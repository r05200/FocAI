// Thin wrappers over the backend REST API (proxied under /api in dev). One function per finished
// route; routes still returning 501 (run event stream, node keep/park/restore, questions,
// replays) are not wrapped yet.

import type {
  CreateVaultRequest,
  Directive,
  DirectiveRequest,
  ExecutionPlan,
  ForkRequest,
  IngestRequest,
  IngestResult,
  Instruction,
  InstructionRequest,
  LogEntry,
  PauseResult,
  Position,
  PreflightRequest,
  PrunerEvent,
  Question,
  Suggestion,
  HumanAction,
  PromptInfo,
  PublicConfig,
  RegenerateLayoutRequest,
  Run,
  RunSnapshot,
  RunVault,
  StartRunRequest,
  StopResult,
  TreeNode,
  VaultGraph,
  VaultSummary,
} from '../types'

export class ApiError extends Error {
  status: number
  // True when the response carried FastAPI's {"detail": ...}, i.e. the backend itself answered.
  fromBackend: boolean
  constructor(status: number, message: string, fromBackend = false) {
    super(message)
    this.status = status
    this.fromBackend = fromBackend
  }
}

// True when the backend couldn't be reached: a network error, or the dev proxy's own 502/504 with
// nothing behind it. A real backend error (even a 500 or 502 with a {"detail"}) is NOT offline, so
// its message is shown instead of being swallowed. Callers use this to fall back to local data.
export function isOffline(err: unknown) {
  return !(err instanceof ApiError) || (!err.fromBackend && (err.status === 404 || err.status >= 500))
}

// `as: 'text'` returns the body as it is (plain-text routes, e.g. the run's patch).
async function request<T>(method: string, path: string, body?: unknown, as: 'json' | 'text' = 'json'): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    // FastAPI errors look like {"detail": "..."} (or a list of validation problems).
    let detail = `${method} ${path} failed (${res.status})`
    let fromBackend = false
    try {
      const j = await res.json()
      if (typeof j.detail === 'string') {
        detail = j.detail
        fromBackend = true
      } else if (Array.isArray(j.detail) && j.detail[0]?.msg) {
        detail = j.detail[0].msg
        fromBackend = true
      }
    } catch {
      /* no JSON body */
    }
    throw new ApiError(res.status, detail, fromBackend)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (as === 'text') return text as T
  return (text ? JSON.parse(text) : undefined) as T
}

const id = encodeURIComponent

// ---- vault
export const listVaults = () => request<VaultSummary[]>('GET', '/vault/vaults')
// 201 -> VaultSummary; 409 if the person already has a vault.
export const createVault = (body: CreateVaultRequest) => request<VaultSummary>('POST', '/vault/vaults', body)
export const getVaultGraph = (person?: string) =>
  request<VaultGraph>('GET', `/vault/graph${person ? `?person=${id(person)}` : ''}`)
// 201 -> the new item plus its links; 502 if the vault LLM fails. `kind` can't be "directive".
export const ingestItem = (body: IngestRequest) => request<IngestResult>('POST', '/vault/items', body)
// 204. The Move tool: where a card now sits (404 if unknown).
export const moveItem = (itemId: string, position: Position) =>
  request<void>('PATCH', `/vault/items/${id(itemId)}/position`, position)
// Recompute every automatic position; moved cards keep their spot unless reset_moved.
export const regenerateLayout = (body: RegenerateLayoutRequest = {}) =>
  request<VaultGraph>('POST', '/vault/layout/regenerate', body)

// ---- directives
export const listDirectives = (person?: string) =>
  request<Directive[]>('GET', `/vault/directives${person ? `?person=${id(person)}` : ''}`)
export const addDirective = (body: DirectiveRequest) => request<Directive>('POST', '/vault/directives', body)
export const deleteDirective = (directiveId: string) =>
  request<void>('DELETE', `/vault/directives/${id(directiveId)}`)

// ---- runs
// 202 -> the new Run. The agent works in the background: follow it with getRun + streamRunEvents.
export const startRun = (body: StartRunRequest) => request<Run>('POST', '/runs', body)
// Before a run starts: the execution order the backend's LLM reads from the question and the files,
// whether the run command is known, and the files the text names that aren't attached. Changes
// nothing. 422 for a bad path, 502 if the LLM fails.
export const preflightRun = (body: PreflightRequest) => request<ExecutionPlan>('POST', '/runs/preflight', body)
// Answer a run's question. For the "command" question the answer becomes the experiment command
// exactly as typed, and the run carries on. 409 if already answered or the run finished.
export const answerQuestion = (runId: string, questionId: string, answer: string) =>
  request<Question>('POST', `/runs/${id(runId)}/questions/${id(questionId)}/answer`, { answer })
export const listRuns = () => request<Run[]>('GET', '/runs')
// The run's current state, its whole tree included. Note the backend saves it at level boundaries,
// so between those it can lag behind the event stream.
export const getRun = (runId: string) => request<RunSnapshot>('GET', `/runs/${id(runId)}`)

const RUN_EVENT_TYPES: PrunerEvent['type'][] = [
  'run_started', 'objectives_updated', 'node_created', 'node_updated', 'instruction_added',
  'vault_retrieved', 'vault_item_added', 'activity', 'question_asked', 'question_answered',
  'run_updated', 'node_log', 'finding_added', 'idea_added', 'suggestions_ready',
  'suggestion_resolved', 'node_removed', 'fork_updated', 'run_completed', 'run_failed',
]

// GET /runs/{id}/events?after=<seq>: SSE, replays the run's events after `after`, then goes live.
// Each event names its `type` as the SSE event name and carries full objects (replace by id).
// `onError(opened)`: the stream closed; `opened` says whether it had connected at all (false = the
// route isn't available, or the backend is down).
// Returns a function that closes it.
export function streamRunEvents(
  runId: string,
  after: number,
  onEvent: (e: PrunerEvent) => void,
  onError: (opened: boolean) => void,
): () => void {
  const source = new EventSource(`/api/runs/${id(runId)}/events?after=${after}`)
  let opened = false
  const handle = (m: MessageEvent<string>) => {
    opened = true
    try {
      onEvent(JSON.parse(m.data) as PrunerEvent)
    } catch (err) {
      console.debug('Unreadable run event:', err)
    }
  }
  for (const type of RUN_EVENT_TYPES) source.addEventListener(type, handle)
  source.onmessage = handle
  source.onopen = () => (opened = true)
  // EventSource would retry on its own; the caller decides (resume after the last seq, or poll).
  source.onerror = () => {
    source.close()
    onError(opened)
  }
  return () => source.close()
}
// 202 -> the recorded Instruction. `directives`, when given, replaces the run's directive list.
export const addInstruction = (runId: string, body: InstructionRequest) =>
  request<Instruction>('POST', `/runs/${id(runId)}/instructions`, body)
// 200 -> the Instruction: turn a steering chip on or off (off = left out of every prompt). 409 if the
// run finished, its objectives aren't written yet, or it's the research spec.
export const toggleInstruction = (runId: string, instructionId: string, active: boolean) =>
  request<Instruction>('PATCH', `/runs/${id(runId)}/instructions/${id(instructionId)}`, { active })
export const listForks = (runId: string) => request<ForkRequest[]>('GET', `/runs/${id(runId)}/forks`)
// The fork card for F, or F moved to `at` (a node on the path, or below F): what it would park, the
// keeps it overrides, the flagged nodes. Changes nothing. 409 if the run finished or `at` doesn't fit.
export const previewFork = (runId: string, forkId: string, at?: string) =>
  request<ForkRequest>('GET', `/runs/${id(runId)}/forks/${id(forkId)}/preview${at ? `?at=${id(at)}` : ''}`)
// Fork: park everything off the root-to-F path (and under F), queue new hypotheses at F, leave the
// run paused. `at` moves F; `keep_live` keeps flagged nodes live. 409 if it's no longer waiting.
export const confirmFork = (runId: string, forkId: string, body: { at?: string | null; keep_live?: string[] }) =>
  request<ForkRequest>('POST', `/runs/${id(runId)}/forks/${id(forkId)}/confirm`, body)
// No fork: nothing is parked; the run carries on with the amended objectives.
export const dismissFork = (runId: string, forkId: string) =>
  request<ForkRequest>('POST', `/runs/${id(runId)}/forks/${id(forkId)}/dismiss`)
// Put the tree back as it was before the fork. If nodes were created since, they're deleted, which
// needs confirm_delete: without it the answer is 409 "Undo fork: this deletes N new node(s)...".
export const undoFork = (runId: string, forkId: string, confirmDelete = false) =>
  request<ForkRequest>('POST', `/runs/${id(runId)}/forks/${id(forkId)}/undo`, { confirm_delete: confirmDelete })

// Where the run could continue from. Confirm acts on it ("run" runs that node next, "restore"
// restores it, "expand"/"remeasure" propose from it); dismiss drops it. 409 if the run finished,
// it was already answered, or it no longer fits.
export const listSuggestions = (runId: string) => request<Suggestion[]>('GET', `/runs/${id(runId)}/suggestions`)
export const confirmSuggestion = (runId: string, suggestionId: string) =>
  request<Suggestion>('POST', `/runs/${id(runId)}/suggestions/${id(suggestionId)}/confirm`)
export const dismissSuggestion = (runId: string, suggestionId: string) =>
  request<Suggestion>('POST', `/runs/${id(runId)}/suggestions/${id(suggestionId)}/dismiss`)

// The changes the run left applied to the user's files, as a unified diff (empty if nothing was
// kept). 404 until the run has finished with files (Run.patch_ready).
export const getPatch = (runId: string) => request<string>('GET', `/runs/${id(runId)}/patch`, undefined, 'text')
// 202 -> cancels the run's in-flight LLM calls and ends it. 404 unknown run, 409 already finished.
export const stopRun = (runId: string) => request<StopResult>('POST', `/runs/${id(runId)}/stop`)

// The run vault (the agent's own discoveries for one run). POST creates it (idempotent; runs the
// backend starts already have one); GET returns it (404 unknown run). New entries also arrive as
// idea_added events.
export const createRunVault = (runId: string) => request<RunVault>('POST', `/runs/${id(runId)}/vault`)
export const getRunVault = (runId: string) => request<RunVault>('GET', `/runs/${id(runId)}/vault`)

// 202 -> { run_id, paused }. Pause: calls already in flight finish, but the run's next step (and any
// step an instruction starts) waits until resume. Pausing a paused run is fine. 404 unknown run,
// 409 already finished. Stop still works while paused.
export const pauseRun = (runId: string) => request<PauseResult>('POST', `/runs/${id(runId)}/pause`)
export const resumeRun = (runId: string) => request<PauseResult>('POST', `/runs/${id(runId)}/resume`)

// POST /api/runs/{id}/manual {manual} -> the Run. On: before each experiment the run waits for a
// person to choose which proposed hypothesis to pursue (the waiting nodes get awaiting_choice, the
// run awaiting "choice"); keep a waiting hypothesis to run it next, park the ones to drop. Off: the
// agent chooses again, at once if it was waiting. 404 unknown run, 409 already finished.
export const setManualMode = (runId: string, manual: boolean) =>
  request<Run>('POST', `/runs/${id(runId)}/manual`, { manual })

// A person's action on a node -> the updated Node (the change also arrives as node_updated).
//   keep: force it to stay (a parked one comes back; a waiting one moves up the queue).
//   park: park it by hand (restorable); on a running node it applies once its step finishes.
//   restore: bring a parked branch back (409 if it isn't parked).
// 404 unknown run or node; 409 if the run finished or the action doesn't fit (the baseline, a
// failed node, the conclusion).
export const nodeAction = (runId: string, nodeId: string, action: HumanAction) =>
  request<TreeNode>('POST', `/runs/${id(runId)}/nodes/${id(nodeId)}/${action}`)

// PROPOSED ROUTE, not in the backend yet: POST /api/runs/{id}/nodes/{node_id}/conclude -> the new
// conclusion Node (type "conclusion", a child of node_id). Ends the run's exploration at this node:
// everything under it is dropped and the conclusion is written from the path to it. The frontend
// draws the conclusion straight away and treats 404 / 405 / 501 (not built yet) as "kept locally".
// 404 unknown run or node, 409 if the run finished or the node can't conclude (the root, a parked
// or failed node, a conclusion).
export const concludeNode = (runId: string, nodeId: string) =>
  request<TreeNode>('POST', `/runs/${id(runId)}/nodes/${id(nodeId)}/conclude`)

// GET /api/runs/{id}/nodes/{node_id}/logs -> LogEntry[], oldest first: the agent's tool calls (each
// with its reason) and results, decisions and errors. New lines also arrive as node_log events.
export const getNodeLogs = (runId: string, nodeId: string) =>
  request<LogEntry[]>('GET', `/runs/${id(runId)}/nodes/${id(nodeId)}/logs`)

// ---- meta
export const getConfig = () => request<PublicConfig>('GET', '/config')
export const listPrompts = () => request<PromptInfo[]>('GET', '/prompts')
