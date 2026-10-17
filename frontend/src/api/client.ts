// Thin wrappers over the backend REST API (proxied under /api).

import type { CreateVaultRequest, Run, StartRunRequest, VaultSummary } from '../types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/**
 * Ask the backend to terminate a run immediately.
 *
 * PROPOSED ROUTE, not in the backend yet: `POST /api/runs/{run_id}/stop` -> 202 (or 409 if the
 * run already finished). The backend side of "stop in its tracks" is described in the handoff
 * notes: cancel the run's asyncio task so the in-flight LLM call is aborted, then emit a final
 * event so every client sees the run end.
 */
export async function stopRun(runId: string): Promise<void> {
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/stop`, { method: 'POST' })
  if (!res.ok && res.status !== 409) throw new ApiError(res.status, `stop failed (${res.status})`)
}

/** Start a run: `POST /api/runs` -> 202 with the new Run. */
export async function startRun(body: StartRunRequest): Promise<Run> {
  const res = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new ApiError(res.status, `start failed (${res.status})`)
  return (await res.json()) as Run
}

/** Create an empty vault: `POST /api/vault/vaults` -> 201 VaultSummary, 409 if it exists. */
export async function createVault(body: CreateVaultRequest): Promise<VaultSummary> {
  const res = await fetch('/api/vault/vaults', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new ApiError(res.status, `create vault failed (${res.status})`)
  return (await res.json()) as VaultSummary
}
