import { create } from 'zustand'
import { ApiError, isOffline, listRuns, pauseRun, resumeRun, setManualMode, stopRun } from '../api/client'
import { isLocalRun } from '../lib/localRun'
import type { ExecutionPlan, PauseResult, Question, Run } from '../types'

// What the prompt bar needs to know about the run being viewed.
//   idle     -> nothing running here; the prompt bar shows Send
//   running  -> the prompt bar shows Pause and Stop
//   paused   -> the agent is holding; the bar shows Play and Stop
//   stopping -> Stop was pressed; waiting for the backend to confirm the run ended
type RunPhase = 'idle' | 'running' | 'paused' | 'stopping'

// Lifecycle of one run: running <-> paused, then (stopping ->) ended.
type RunLife = 'running' | 'paused' | 'stopping' | 'ended'

interface RunEntry {
  id: string
  question: string
  life: RunLife
  startedAt: number
}

// The viewed run's command state, for the notice under the prompt bar. Published by the run's tree,
// which holds the run's live state (snapshot + event stream).
export interface RunCommandState {
  runId: string
  plan: ExecutionPlan | null
  commandKnown: boolean
  hasFiles: boolean
  question: Question | null // the pending "command" question, if the run is waiting on it
}

interface RunState {
  commandState: RunCommandState | null
  setCommandState: (s: RunCommandState | null) => void
  // Manual mode per run id, as last set from this browser (the switch next to the prompt bar);
  // otherwise the run's own Run.manual applies (`serverManual`, published by the run's tree). The
  // backend is told on every flip (POST /runs/{id}/manual); its answer (the run) is kept in
  // `manualReply` for the tree to put on screen at once.
  manual: Record<string, boolean>
  setManual: (runId: string, manual: boolean, before: boolean) => Promise<void>
  serverManual: Record<string, boolean>
  setServerManual: (runId: string, manual: boolean) => void
  manualReply: Run | null
  // The main menu's switch: whether the next run starts in manual mode (sent with POST /runs). Kept
  // as set between runs.
  draftManual: boolean
  setDraftManual: (manual: boolean) => void
  // Every run started in this session (newest last). Runs keep going while you're on the main
  // menu; the menu lists the ones still running.
  runs: RunEntry[]
  // The run whose tree is on screen; null = the main menu.
  viewingId: string | null
  // True while that run's vault (the agent's discoveries) is shown instead of its tree.
  runVaultOpen: boolean
  openRunVault: () => void
  closeRunVault: () => void
  // FLAG (ignore unless asked): `error` is set on a failed stop but nothing renders it, and it is cleared right after.
  error: string | null
  // Held per run so Stop can cut its live event stream (SSE) the moment it's pressed.
  streams: Record<string, AbortController>
  // Start tracking a run and show it.
  begin: (runId: string, question: string, streamAbort?: AbortController) => void
  // Stop the run on screen (or the given one).
  stop: (runId?: string) => Promise<void>
  // Hold the run's agent before its next step / let it carry on. Throw when the backend refuses
  // (e.g. it doesn't have the route yet); the run's state is then left as it was.
  pause: (runId?: string) => Promise<void>
  resume: (runId?: string) => Promise<void>
  // Call when the stream reports a run ended (done / failed / cancelled).
  finish: (runId: string) => void
  // Back to the main menu; the run keeps going.
  leave: () => void
  // What's typed in the prompt bar. Going from the main menu into a run (its list, or History)
  // puts the main menu's draft aside and empties the bar; going back brings the draft back.
  prompt: string
  setPrompt: (prompt: string) => void
  mainDraft: string
  // Show a run's tree (e.g. from the main menu's list).
  open: (runId: string) => void
  // Show a run known only from the backend (a past run from History): track it, then show it.
  openRun: (run: Run) => void
  // Reconcile with GET /runs: pick up runs still running that this session didn't start (e.g. after
  // a reload) and mark tracked runs the backend says have ended. The live event stream isn't built
  // yet, so this is how the UI learns a run finished. Silent when the backend is unreachable.
  syncRuns: () => Promise<void>
}

// Leaving the main menu for a run: keep its draft for later and start the bar empty. (Moving
// between runs keeps the draft already put aside.)
const setDraftAside = (s: RunState): Partial<RunState> =>
  s.viewingId === null ? { mainDraft: s.prompt, prompt: '' } : { prompt: '' }

const fromRun = (r: Run): RunEntry => ({
  id: r.id,
  question: r.question,
  life: r.status !== 'running' ? 'ended' : r.paused ? 'paused' : 'running',
  startedAt: r.created_at * 1000,
})

// Pause or resume: ask the backend and record what it says (`paused` in its answer). A run that only
// exists in the browser (backend unreachable) just changes locally.
async function hold(
  get: () => RunState,
  set: (fn: (s: RunState) => Partial<RunState>) => void,
  runId: string | undefined,
  pausing: boolean,
  call: (id: string) => Promise<PauseResult>,
) {
  const id = runId ?? get().viewingId
  const life = () => get().runs.find((r) => r.id === id)?.life
  if (!id || life() !== (pausing ? 'running' : 'paused')) return
  let paused = pausing
  try {
    paused = (await call(id)).paused
  } catch (err) {
    // 409: the run finished while we weren't looking.
    if (err instanceof ApiError && err.status === 409) {
      get().finish(id)
      throw new Error('That run has already finished.', { cause: err })
    }
    if (!isOffline(err)) throw err
  }
  // The run may have been stopped while the request was in flight.
  if (life() === 'running' || life() === 'paused') {
    set((s) => ({ runs: setLife(s.runs, id, paused ? 'paused' : 'running') }))
  }
}

const setLife = (runs: RunEntry[], id: string, life: RunLife) =>
  runs.map((r) => (r.id === id ? { ...r, life } : r))

export const useRunStore = create<RunState>()((set, get) => ({
  commandState: null,
  setCommandState: (commandState) => set({ commandState }),
  manual: {},
  setManual: async (runId, manual, before) => {
    set((s) => ({ manual: { ...s.manual, [runId]: manual } }))
    if (isLocalRun(runId)) return // nothing on the backend to tell
    try {
      const run = await setManualMode(runId, manual)
      // Only while its tree is on screen to take it: otherwise a later mount would lay this (by then
      // stale) run over the fresh snapshot.
      set((s) => ({
        manual: { ...s.manual, [runId]: run?.manual ?? manual },
        ...(run && s.viewingId === runId ? { manualReply: run } : {}),
      }))
    } catch (err) {
      if (isOffline(err)) return // no backend: the switch just stays as set
      set((s) => ({ manual: { ...s.manual, [runId]: before } })) // the backend refused: put it back
      throw err
    }
  },
  serverManual: {},
  setServerManual: (runId, manual) =>
    set((s) => (s.serverManual[runId] === manual ? {} : { serverManual: { ...s.serverManual, [runId]: manual } })),
  manualReply: null,
  draftManual: false,
  setDraftManual: (draftManual) => set({ draftManual }),
  runs: [],
  viewingId: null,
  runVaultOpen: false,
  error: null,
  streams: {},

  begin: (runId, question, streamAbort) =>
    set((s) => ({
      // A poll (syncRuns) may have picked the new run up already: replace that entry, don't add a second.
      runs: [...s.runs.filter((r) => r.id !== runId), { id: runId, question, life: 'running', startedAt: Date.now() }],
      // It was started with the main menu's switch as it is now.
      manual: { ...s.manual, [runId]: s.draftManual },
      viewingId: runId,
      runVaultOpen: false,
      error: null,
      // The question just sent was the draft: nothing to bring back.
      prompt: '',
      mainDraft: '',
      streams: streamAbort ? { ...s.streams, [runId]: streamAbort } : s.streams,
    })),

  // FLAG (ignore unless asked): comment says 'cancelled', but RunStatus has no cancelled state and no cancel event exists.
  stop: async (runId) => {
    const id = runId ?? get().viewingId
    const run = get().runs.find((r) => r.id === id)
    if (!id || (run?.life !== 'running' && run?.life !== 'paused')) return
    const before = run!.life
    set((s) => ({ runs: setLife(s.runs, id, 'stopping') }))
    get().streams[id]?.abort() // stop listening locally, so the UI freezes on the last event
    // Tell the backend to kill the run (this is what actually halts the LLM). A run only in the
    // browser ends here at once; so does one the backend says is already over (409) or doesn't
    // know any more (404).
    try {
      if (!isLocalRun(id)) await stopRun(id)
    } catch (e) {
      const over = e instanceof ApiError && e.fromBackend && (e.status === 409 || e.status === 404)
      if (!over) {
        // Refused, failed, or the backend couldn't be reached: the run may well still be going
        // there, so it stays going here (Stop stays available) and the reason is shown.
        set((s) => ({ runs: setLife(s.runs, id, before) }))
        throw isOffline(e) ? new Error('Couldn’t reach the backend, so the run may still be going. Try Stop again.', { cause: e }) : e
      }
    }
    get().finish(id)
  },

  pause: (runId) => hold(get, set, runId, true, pauseRun),
  resume: (runId) => hold(get, set, runId, false, resumeRun),

  finish: (runId) =>
    set((s) => {
      const streams = { ...s.streams }
      delete streams[runId]
      return { runs: setLife(s.runs, runId, 'ended'), streams }
    }),

  leave: () => set((s) => ({ viewingId: null, runVaultOpen: false, prompt: s.mainDraft, mainDraft: '' })),
  open: (runId) => set((s) => ({ viewingId: runId, runVaultOpen: false, ...setDraftAside(s) })),
  prompt: '',
  setPrompt: (prompt) => set({ prompt }),
  mainDraft: '',
  openRunVault: () => set((s) => (s.viewingId ? { runVaultOpen: true } : {})),
  closeRunVault: () => set({ runVaultOpen: false }),

  openRun: (run) =>
    set((s) => ({
      runs: s.runs.some((r) => r.id === run.id) ? s.runs : [...s.runs, fromRun(run)],
      viewingId: run.id,
      runVaultOpen: false,
      ...setDraftAside(s),
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
        if (r.life !== 'running' && r.life !== 'paused') return r
        // The backend no longer has it (its run data was reset): it's over. Runs that only exist
        // in the browser, and ones started moments ago (this list may predate them), are left be.
        if (!srv) return isLocalRun(r.id) || Date.now() - r.startedAt < FORGOTTEN_AFTER_MS ? r : { ...r, life: 'ended' as const }
        // Ended on the backend -> ended here; otherwise follow its paused flag (it may have been
        // paused or resumed from another tab).
        const life = fromRun(srv).life
        return life === r.life ? r : { ...r, life }
      })
      const fresh = server.filter((r) => r.status === 'running' && !known.has(r.id)).map(fromRun)
      return fresh.length || runs.some((r, i) => r !== s.runs[i]) ? { runs: [...runs, ...fresh] } : {}
    })
  },
}))

// A tracked run missing from GET /runs for longer than this is taken as gone.
const FORGOTTEN_AFTER_MS = 30_000

// The prompt bar's view of the run on screen.
export function selectPhase(s: RunState): RunPhase {
  const life = s.runs.find((r) => r.id === s.viewingId)?.life
  return life === undefined || life === 'ended' ? 'idle' : life
}

// Runs still going, newest first (what the main menu lists).
export function selectRunning(runs: RunEntry[]): RunEntry[] {
  return runs.filter((r) => r.life !== 'ended').reverse()
}
