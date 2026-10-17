// Thin wrappers over the backend REST API (proxied under /api in dev). One function per finished
// route; routes still returning 501 (run event stream, node keep/park/restore, questions,
// replays) are not wrapped yet.

import type {
  CreateVaultRequest,
  Directive,
  DirectiveRequest,
  ForkRequest,
  IngestRequest,
  IngestResult,
  Instruction,
  InstructionRequest,
  LogEntry,
  PauseResult,
  Position,
  PrunerEvent,
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
  VaultItemView,
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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
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
  return (text ? JSON.parse(text) : undefined) as T
}

const id = encodeURIComponent

// ---- vault
export const listPeople = () => request<string[]>('GET', '/vault/people')
export const listVaults = () => request<VaultSummary[]>('GET', '/vault/vaults')
// 201 -> VaultSummary; 409 if the person already has a vault.
export const createVault = (body: CreateVaultRequest) => request<VaultSummary>('POST', '/vault/vaults', body)
export const getVaultGraph = (person?: string) =>
  request<VaultGraph>('GET', `/vault/graph${person ? `?person=${id(person)}` : ''}`)
export const getVaultItem = (itemId: string) => request<VaultItemView>('GET', `/vault/items/${id(itemId)}`)
// 201 -> the new item plus its links; 502 if the vault LLM fails. `kind` can't be "directive".
export const ingestItem = (body: IngestRequest) => request<IngestResult>('POST', '/vault/items', body)
// 204. The Move tool: where a card now sits (404 if unknown).
export const moveItem = (itemId: string, position: Position) =>
  request<void>('PATCH', `/vault/items/${id(itemId)}/position`, position)
export const moveItems = (positions: (Position & { id: string })[]) =>
  request<void>('PATCH', '/vault/positions', { positions })
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
export const listRuns = () => request<Run[]>('GET', '/runs')
// The run's current state, its whole tree included. Note the backend saves it at level boundaries,
// so between those it can lag behind the event stream.
export const getRun = (runId: string) => request<RunSnapshot>('GET', `/runs/${id(runId)}`)

const RUN_EVENT_TYPES: PrunerEvent['type'][] = [
  'run_started', 'objectives_updated', 'node_created', 'node_updated', 'instruction_added',
  'vault_retrieved', 'vault_item_added', 'activity', 'question_asked', 'question_answered',
  'run_completed', 'run_failed',
]

// GET /runs/{id}/events?after=<seq>: SSE, replays the run's events after `after`, then goes live.
// Each event names its `type` as the SSE event name and carries full objects (replace by id).
// `onError(opened)`: the stream closed; `opened` says whether it had connected at all (false = the
// route isn't available, e.g. the backend's current 501 "not implemented", or the backend is down).
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
export const listForks = (runId: string) => request<ForkRequest[]>('GET', `/runs/${id(runId)}/forks`)
// 202 -> cancels the run's in-flight LLM calls and ends it. 404 unknown run, 409 already finished.
export const stopRun = (runId: string) => request<StopResult>('POST', `/runs/${id(runId)}/stop`)

// PROPOSED ROUTES for the run vault (the agent's own discoveries for one run), not in the backend:
//   POST /api/runs/{id}/vault -> 201 RunVault. Creates the run's (empty) vault and saves it to disk
//     with the run (e.g. data/runs/<id>/vault.json). Idempotent: an existing vault comes back as is.
//     The frontend calls it right after a run starts; the backend may equally create it inside
//     start_run (then this just returns it).
//   GET /api/runs/{id}/vault  -> RunVault (404 unknown run).
export const createRunVault = (runId: string) => request<RunVault>('POST', `/runs/${id(runId)}/vault`)
export const getRunVault = (runId: string) => request<RunVault>('GET', `/runs/${id(runId)}/vault`)

// 202 -> { run_id, paused }. Pause: calls already in flight finish, but the run's next step (and any
// step an instruction starts) waits until resume. Pausing a paused run is fine. 404 unknown run,
// 409 already finished. Stop still works while paused.
export const pauseRun = (runId: string) => request<PauseResult>('POST', `/runs/${id(runId)}/pause`)
export const resumeRun = (runId: string) => request<PauseResult>('POST', `/runs/${id(runId)}/resume`)

// POST /runs/{id}/nodes/{node_id}/park -> the updated Node: parks a branch by hand (restorable). The
// route exists but still answers 501 "not implemented"; the same change arrives as node_updated.
export const parkNode = (runId: string, nodeId: string) =>
  request<TreeNode>('POST', `/runs/${id(runId)}/nodes/${id(nodeId)}/park`)

// PROPOSED ROUTE, not in the backend yet: GET /api/runs/{id}/nodes/{node_id}/logs -> LogEntry[],
// oldest first: the node's reasoning steps, every tool call with its arguments and result, and its
// scoring decisions. The agent has no tool loop yet (backend/pruner/agent/tools.py), so today a
// backend could only log the plan and the answer.
export const getNodeLogs = (runId: string, nodeId: string) =>
  request<LogEntry[]>('GET', `/runs/${id(runId)}/nodes/${id(nodeId)}/logs`)

// ---- meta
export const getConfig = () => request<PublicConfig>('GET', '/config')
export const listPrompts = () => request<PromptInfo[]>('GET', '/prompts')
export const getPrompt = (name: string) => request<PromptInfo>('GET', `/prompts/${id(name)}`)
