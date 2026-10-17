import { create } from 'zustand'
import { stopRun } from '../api/client'

// Lifecycle of the run started from the prompt box.
//   idle     -> nothing running; the prompt box shows Send
//   running  -> the prompt box shows Stop
//   stopping -> Stop was pressed; waiting for the backend to confirm the run ended
export type RunPhase = 'idle' | 'running' | 'stopping'

interface RunState {
  phase: RunPhase
  runId: string | null
  error: string | null
  // Held so Stop can cut the live event stream (SSE) the moment it's pressed.
  streamAbort: AbortController | null
  begin: (runId: string, streamAbort?: AbortController) => void
  stop: () => Promise<void>
  // Call when the stream reports the run ended (done / failed / cancelled).
  finish: () => void
}

export const useRunStore = create<RunState>()((set, get) => ({
  phase: 'idle',
  runId: null,
  error: null,
  streamAbort: null,

  begin: (runId, streamAbort) =>
    set({ phase: 'running', runId, error: null, streamAbort: streamAbort ?? null }),

  stop: async () => {
    const { phase, runId, streamAbort } = get()
    if (phase !== 'running' || !runId) return
    set({ phase: 'stopping' })
    // 1. Stop listening locally so the UI freezes on the last event immediately.
    streamAbort?.abort()
    // 2. Tell the backend to kill the run (this is what actually halts the LLM).
    try {
      await stopRun(runId)
    } catch (e) {
      // Even if the call failed, don't leave the UI stuck on "stopping".
      set({ error: e instanceof Error ? e.message : 'Could not stop the run' })
    }
    set({ phase: 'idle', runId: null, streamAbort: null })
  },

  finish: () => set({ phase: 'idle', runId: null, streamAbort: null }),
}))
