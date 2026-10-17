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
  Position,
  PromptInfo,
  PublicConfig,
  RegenerateLayoutRequest,
  Run,
  RunSnapshot,
  StartRunRequest,
  StopResult,
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
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
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
// 202 -> the new Run. The agent works in the background; the live event stream isn't built yet, so
// follow it with getRun / listRuns.
export const startRun = (body: StartRunRequest) => request<Run>('POST', '/runs', body)
export const listRuns = () => request<Run[]>('GET', '/runs')
export const getRun = (runId: string) => request<RunSnapshot>('GET', `/runs/${id(runId)}`)
// 202 -> the recorded Instruction. `directives`, when given, replaces the run's directive list.
export const addInstruction = (runId: string, body: InstructionRequest) =>
  request<Instruction>('POST', `/runs/${id(runId)}/instructions`, body)
export const listForks = (runId: string) => request<ForkRequest[]>('GET', `/runs/${id(runId)}/forks`)
// 202 -> cancels the run's in-flight LLM calls and ends it. 404 unknown run, 409 already finished.
export const stopRun = (runId: string) => request<StopResult>('POST', `/runs/${id(runId)}/stop`)

// ---- meta
export const getConfig = () => request<PublicConfig>('GET', '/config')
export const listPrompts = () => request<PromptInfo[]>('GET', '/prompts')
export const getPrompt = (name: string) => request<PromptInfo>('GET', `/prompts/${id(name)}`)
