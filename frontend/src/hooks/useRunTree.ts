import { useCallback, useEffect, useRef, useState } from 'react'
import { getRun, isOffline, streamRunEvents } from '../api/client'
import { isLocalRun } from '../lib/localRun'
import type {
  Finding,
  ForkRequest,
  Instruction,
  LogEntry,
  Objective,
  PrunerEvent,
  Question,
  Run,
  RunSnapshot,
  Suggestion,
  TreeNode,
} from '../types'

// 'sample': the run only exists in the browser (or the backend is unreachable): there are no real
// nodes, so the tree shows its stand-in. 'missing': the backend doesn't know the run.
type SnapshotStatus = 'loading' | 'ok' | 'sample' | 'missing'

// Polling interval while the event stream isn't available, and the wait before resuming a stream
// that dropped.
const POLL_MS = 3000
const RECONNECT_MS = 1000
const RETRY_STREAM_MS = 5000
// New events are applied together in one render, at most this often.
const FLUSH_MS = 30

// What the event stream (and the UI's own actions) changed on top of the last GET /runs/{id}.
// Every event carries whole objects, so each map is "replace by id".
export interface Overlay {
  run: Run | null // run_started / run_updated / run_completed carry the whole run
  objectives: Objective[] | null // objectives_updated, newer than `run`
  instructions: Map<string, Instruction> // instruction_added, newer than `run`
  nodes: Map<string, TreeNode>
  removed: Set<string> // node_removed: gone, even if an older snapshot still has them
  questions: Map<string, Question>
  suggestions: Map<string, Suggestion>
  findings: Map<string, Finding>
  forks: Map<string, ForkRequest> // fork_updated (GET /forks has the rest)
  logs: Map<string, LogEntry[]> // node_log, per node id
}

const emptyOverlay = (): Overlay => ({
  run: null,
  objectives: null,
  instructions: new Map(),
  nodes: new Map(),
  removed: new Set(),
  questions: new Map(),
  suggestions: new Map(),
  findings: new Map(),
  forks: new Map(),
  logs: new Map(),
})

// The base list with the overlay's versions swapped in, then the overlay's new ones in the order
// they arrived (for nodes: parents before children).
function mergeById<T extends { id: string }>(base: readonly T[], over: Map<string, T>): T[] {
  if (over.size === 0) return [...base]
  const known = new Set(base.map((x) => x.id))
  return [...base.map((x) => over.get(x.id) ?? x), ...[...over.values()].filter((x) => !known.has(x.id))]
}

function mergeSnapshot(base: RunSnapshot, o: Overlay): RunSnapshot {
  const run = o.run ?? base.run
  return {
    ...base,
    run: {
      ...run,
      objectives: o.objectives ?? run.objectives,
      instructions: mergeById(run.instructions, o.instructions),
    },
    nodes: mergeById(base.nodes, o.nodes).filter((n) => !o.removed.has(n.id)),
    questions: mergeById(base.questions, o.questions),
    suggestions: mergeById(base.suggestions ?? [], o.suggestions),
    findings: mergeById(base.findings ?? [], o.findings),
  }
}

// Folds one event into the overlay. Returns true when it ends the run.
function applyEvent(o: Overlay, e: PrunerEvent): boolean {
  switch (e.type) {
    case 'node_created':
    case 'node_updated':
      o.nodes.set(e.node.id, e.node)
      o.removed.delete(e.node.id) // ids can be reused after a removal
      break
    case 'node_removed':
      o.nodes.delete(e.node_id)
      o.removed.add(e.node_id)
      break
    case 'run_started':
    case 'run_updated':
    case 'run_completed':
      // The whole run, objectives and instructions included: earlier partial updates are older.
      o.run = e.run
      o.objectives = null
      o.instructions.clear()
      break
    case 'objectives_updated':
      o.objectives = e.objectives
      break
    case 'instruction_added':
      o.instructions.set(e.instruction.id, e.instruction)
      break
    case 'question_asked':
    case 'question_answered':
      o.questions.set(e.question.id, e.question)
      break
    case 'suggestions_ready':
      for (const s of e.suggestions) o.suggestions.set(s.id, s)
      for (const id of e.replaced) {
        const old = o.suggestions.get(id)
        if (old) o.suggestions.set(id, { ...old, status: 'replaced' })
      }
      break
    case 'suggestion_resolved':
      o.suggestions.set(e.suggestion.id, e.suggestion)
      break
    case 'fork_updated':
      o.forks.set(e.fork.id, e.fork)
      break
    case 'finding_added':
      o.findings.set(e.finding.id, e.finding)
      break
    case 'node_log': {
      const list = o.logs.get(e.node_id) ?? []
      if (!list.some((x) => x.id === e.entry.id)) o.logs.set(e.node_id, [...list, e.entry])
      break
    }
  }
  return e.type === 'run_completed' || e.type === 'run_failed'
}

interface Loaded {
  runId: string
  status: SnapshotStatus
  snapshot: RunSnapshot | null
  logs: ReadonlyMap<string, LogEntry[]>
  forks: ReadonlyMap<string, ForkRequest>
}

export interface RunTree {
  snapshot: RunSnapshot | null
  status: SnapshotStatus
  // Node log lines that arrived live (node_log), per node id.
  logs: ReadonlyMap<string, LogEntry[]>
  // Forks that changed live (fork_updated) or by the UI's own actions, by id.
  forks: ReadonlyMap<string, ForkRequest>
  // Fold a change the UI made itself (e.g. the node a keep/park returned) into the run straight
  // away, before the stream or the next poll confirms it.
  apply: (change: (o: Overlay) => void) => void
}

const NO_LOGS: ReadonlyMap<string, LogEntry[]> = new Map()
const NO_FORKS: ReadonlyMap<string, ForkRequest> = new Map()

// A run's state, from the backend: GET /runs/{id} for where it stands, then, while `live`, every
// change from the run's event stream (GET /runs/{id}/events): nodes, the run itself, questions,
// suggestions, findings and node log lines. The stream replays the run from the start, so it also
// fills in anything the saved snapshot is missing. While the stream isn't available the snapshot
// is polled instead.
export function useRunTree(runId: string | null, live: boolean): RunTree {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const applyRef = useRef<RunTree['apply'] | null>(null)

  useEffect(() => {
    if (!runId || isLocalRun(runId)) return
    let cancelled = false
    let base: RunSnapshot | null = null
    let overlay = emptyOverlay()
    let lastSeq = 0
    let ended = false
    let streaming = false // the stream has delivered: it, not polling, keeps the run current
    let poll: ReturnType<typeof setInterval> | undefined
    let flush: ReturnType<typeof setTimeout> | undefined
    let reconnect: ReturnType<typeof setTimeout> | undefined
    let closeStream: (() => void) | undefined

    const publish = () => {
      flush = undefined
      if (cancelled || !base) return
      setLoaded({ runId, status: 'ok', snapshot: mergeSnapshot(base, overlay), logs: new Map(overlay.logs), forks: new Map(overlay.forks) })
    }
    const schedulePublish = () => {
      flush ??= setTimeout(publish, FLUSH_MS)
    }
    applyRef.current = (change) => {
      change(overlay)
      schedulePublish()
    }
    const load = () =>
      getRun(runId).then(
        (snapshot) => {
          base = snapshot
          // Once there's a snapshot, polling only goes on while it's what keeps the run current.
          if (streaming || !live) {
            clearInterval(poll)
            poll = undefined
          }
          // Polling: a fresh snapshot is the whole truth, so local changes laid on top of the last
          // one are dropped (the backend has them, or refused them). Live log lines are kept.
          if (!streaming) overlay = { ...emptyOverlay(), logs: overlay.logs, forks: overlay.forks }
          publish()
        },
        (err) => {
          // A failed refresh keeps what's on screen; a failed first load falls back, and is retried.
          if (cancelled || base) return
          setLoaded({ runId, status: isOffline(err) ? 'sample' : 'missing', snapshot: null, logs: NO_LOGS, forks: NO_FORKS })
          startPolling()
        },
      )
    const startPolling = () => {
      poll ??= setInterval(() => void load(), POLL_MS)
    }
    // Without a working stream the snapshot is the truth: drop what the stream laid on top of it
    // (it would hide every newer poll), and poll.
    const fallBackToPolling = () => {
      streaming = false
      // The overlay goes, so a later stream must replay from the start (the saved snapshot lags).
      lastSeq = 0
      overlay = { ...emptyOverlay(), logs: overlay.logs, forks: overlay.forks }
      startPolling()
    }
    const connect = () => {
      closeStream = streamRunEvents(
        runId,
        lastSeq,
        (e) => {
          streaming = true
          clearInterval(poll)
          poll = undefined
          lastSeq = Math.max(lastSeq, e.seq)
          if (applyEvent(overlay, e)) {
            ended = true
            void load() // the final run state
          }
          schedulePublish()
        },
        (opened) => {
          if (cancelled || ended) return
          if (opened) reconnect = setTimeout(connect, RECONNECT_MS) // dropped: carry on after lastSeq
          else if (streaming) {
            // It delivered before but won't come back (backend restarting): poll, and try again.
            fallBackToPolling()
            reconnect = setTimeout(connect, RETRY_STREAM_MS)
          } else startPolling()
        },
      )
    }

    void load()
    if (live) connect()
    return () => {
      cancelled = true
      applyRef.current = null
      closeStream?.()
      clearInterval(poll)
      clearTimeout(flush)
      clearTimeout(reconnect)
    }
  }, [runId, live])

  const apply = useCallback<RunTree['apply']>((change) => applyRef.current?.(change), [])

  if (runId && isLocalRun(runId)) return { snapshot: null, status: 'sample', logs: NO_LOGS, forks: NO_FORKS, apply }
  const current = loaded && loaded.runId === runId ? loaded : null
  return {
    snapshot: current?.snapshot ?? null,
    status: current?.status ?? 'loading',
    logs: current?.logs ?? NO_LOGS,
    forks: current?.forks ?? NO_FORKS,
    apply,
  }
}
