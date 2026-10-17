import { create } from 'zustand'
import { listRuns, stopRun } from '../api/client'
import type { Run } from '../types'

// What the prompt bar needs to know about the run being viewed.
//   idle     -> nothing running here; the prompt bar shows Send
//   running  -> the prompt bar shows Stop
//   stopping -> Stop was pressed; waiting for the backend to confirm the run ended
export type RunPhase = 'idle' | 'running' | 'stopping'

// Lifecycle of one run: running -> (stopping ->) ended.
export type RunLife = 'running' | 'stopping' | 'ended'

export interface RunEntry {
  id: string
  question: string
  life: RunLife
  startedAt: number
}

interface RunState {
  // Every run started in this session (newest last). Runs keep going while you're on the main
  // menu; the menu lists the ones still running.
  runs: RunEntry[]
  // The run whose tree is on screen; null = the main menu.
  viewingId: string | null
  // FLAG (ignore unless asked): `error` is set on a failed stop but nothing renders it, and it is cleared right after.
  error: string | null
  // Held per run so Stop can cut its live event stream (SSE) the moment it's pressed.
  streams: Record<string, AbortController>
  // Start tracking a run and show it.
  begin: (runId: string, question: string, streamAbort?: AbortController) => void
  // Stop the run on screen (or the given one).
  stop: (runId?: string) => Promise<void>
  // Call when the stream reports a run ended (done / failed / cancelled).
  finish: (runId: string) => void
  // Back to the main menu; the run keeps going.
  leave: () => void
  // Show a run's tree (e.g. from the main menu's list).
  open: (runId: string) => void
  // Show a run known only from the backend (a past run from History): track it, then show it.
  openRun: (run: Run) => void
  // Reconcile with GET /runs: pick up runs still running that this session didn't start (e.g. after
  // a reload) and mark tracked runs the backend says have ended. The live event stream isn't built
  // yet, so this is how the UI learns a run finished. Silent when the backend is unreachable.
  syncRuns: () => Promise<void>
}

const fromRun = (r: Run): RunEntry => ({
  id: r.id,
  question: r.question,
  life: r.status === 'running' ? 'running' : 'ended',
  startedAt: r.created_at * 1000,
})

const setLife = (runs: RunEntry[], id: string, life: RunLife) =>
  runs.map((r) => (r.id === id ? { ...r, life } : r))

export const useRunStore = create<RunState>()((set, get) => ({
  runs: [],
  viewingId: null,
  error: null,
  streams: {},

  begin: (runId, question, streamAbort) =>
    set((s) => ({
      runs: [...s.runs, { id: runId, question, life: 'running', startedAt: Date.now() }],
      viewingId: runId,
      error: null,
      streams: streamAbort ? { ...s.streams, [runId]: streamAbort } : s.streams,
    })),

  // FLAG (ignore unless asked): comment says 'cancelled', but RunStatus has no cancelled state and no cancel event exists.
  stop: async (runId) => {
    const id = runId ?? get().viewingId
    const run = get().runs.find((r) => r.id === id)
    if (!id || run?.life !== 'running') return
    set((s) => ({ runs: setLife(s.runs, id, 'stopping') }))
    // 1. Stop listening locally so the UI freezes on the last event immediately.
    get().streams[id]?.abort()
    // 2. Tell the backend to kill the run (this is what actually halts the LLM).
    try {
      await stopRun(id)
    } catch (e) {
      // Even if the call failed, don't leave the UI stuck on "stopping".
      set({ error: e instanceof Error ? e.message : 'Could not stop the run' })
    }
    get().finish(id)
  },

  finish: (runId) =>
    set((s) => {
      const streams = { ...s.streams }
      delete streams[runId]
      return { runs: setLife(s.runs, runId, 'ended'), streams }
    }),

  leave: () => set({ viewingId: null }),
  open: (runId) => set({ viewingId: runId }),

  openRun: (run) =>
    set((s) => ({
      runs: s.runs.some((r) => r.id === run.id) ? s.runs : [...s.runs, fromRun(run)],
      viewingId: run.id,
    })),

  syncRuns: async () => {
    let server: Run[]
    try {
      server = await listRuns()
    } catch {
      return
    }
    set((s) => {
      const byId = new Map(server.map((r) => [r.id, r]))
      const known = new Set(s.runs.map((r) => r.id))
      const runs = s.runs.map((r) => {
        const srv = byId.get(r.id)
        // Only ever running -> ended here; "stopping" is settled by the stop call itself.
        return srv && srv.status !== 'running' && r.life === 'running' ? { ...r, life: 'ended' as const } : r
      })
      const fresh = server.filter((r) => r.status === 'running' && !known.has(r.id)).map(fromRun)
      return fresh.length || runs.some((r, i) => r !== s.runs[i]) ? { runs: [...runs, ...fresh] } : {}
    })
  },
}))

// The prompt bar's view of the run on screen.
export function selectPhase(s: RunState): RunPhase {
  const life = s.runs.find((r) => r.id === s.viewingId)?.life
  return life === 'running' || life === 'stopping' ? life : 'idle'
}

// Runs still going, newest first (what the main menu lists).
export function selectRunning(runs: RunEntry[]): RunEntry[] {
  return runs.filter((r) => r.life !== 'ended').reverse()
}
