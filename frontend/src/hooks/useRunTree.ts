import { useEffect, useState } from 'react'
import { getRun, isOffline, streamRunEvents } from '../api/client'
import { isLocalRun } from '../lib/localRun'
import type { RunSnapshot, TreeNode } from '../types'

// 'sample': the run only exists in the browser (or the backend is unreachable): there are no real
// nodes, so the tree shows its stand-in. 'missing': the backend doesn't know the run.
export type SnapshotStatus = 'loading' | 'ok' | 'sample' | 'missing'

// Polling interval while the event stream isn't available, and the wait before resuming a stream
// that dropped.
const POLL_MS = 3000
const RECONNECT_MS = 1000
// New events are applied together in one render, at most this often.
const FLUSH_MS = 30

interface Loaded {
  runId: string
  status: SnapshotStatus
  snapshot: RunSnapshot | null
}

// The snapshot's nodes with the streamed versions swapped in, then streamed nodes it doesn't have
// yet, in the order they were created (parents before children).
function merge(base: TreeNode[], streamed: Map<string, TreeNode>): TreeNode[] {
  if (streamed.size === 0) return base
  const known = new Set(base.map((n) => n.id))
  return [...base.map((n) => streamed.get(n.id) ?? n), ...[...streamed.values()].filter((n) => !known.has(n.id))]
}

// A run's tree, from the backend: GET /runs/{id} for the current structure, then, while `live`, new
// and changed nodes from the run's event stream (GET /runs/{id}/events). The stream replays the run
// from the start, so it also fills in anything the saved snapshot is missing. While the stream
// isn't available (the backend doesn't serve it yet) the snapshot is polled instead.
export function useRunTree(runId: string | null, live: boolean): { snapshot: RunSnapshot | null; status: SnapshotStatus } {
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    if (!runId || isLocalRun(runId)) return
    let cancelled = false
    let base: RunSnapshot | null = null
    const streamed = new Map<string, TreeNode>()
    let lastSeq = 0
    let ended = false
    let poll: ReturnType<typeof setInterval> | undefined
    let flush: ReturnType<typeof setTimeout> | undefined
    let reconnect: ReturnType<typeof setTimeout> | undefined
    let closeStream: (() => void) | undefined

    const publish = () => {
      flush = undefined
      if (cancelled || !base) return
      setLoaded({ runId, status: 'ok', snapshot: { ...base, nodes: merge(base.nodes, streamed) } })
    }
    const schedulePublish = () => {
      flush ??= setTimeout(publish, FLUSH_MS)
    }
    const load = () =>
      getRun(runId).then(
        (snapshot) => {
          base = snapshot
          publish()
        },
        (err) => {
          // A failed refresh keeps what's on screen; only a first load falls back.
          if (cancelled || base) return
          setLoaded({ runId, status: isOffline(err) ? 'sample' : 'missing', snapshot: null })
        },
      )
    const startPolling = () => {
      poll ??= setInterval(() => void load(), POLL_MS)
    }
    const connect = () => {
      closeStream = streamRunEvents(
        runId,
        lastSeq,
        (e) => {
          lastSeq = Math.max(lastSeq, e.seq)
          if (e.type === 'node_created' || e.type === 'node_updated') {
            streamed.set(e.node.id, e.node)
            schedulePublish()
          } else if (e.type === 'run_completed' || e.type === 'run_failed') {
            ended = true
            void load() // the final run state
          }
        },
        (opened) => {
          if (cancelled || ended) return
          if (opened) reconnect = setTimeout(connect, RECONNECT_MS) // dropped: carry on after lastSeq
          else startPolling()
        },
      )
    }

    void load()
    if (live) connect()
    return () => {
      cancelled = true
      closeStream?.()
      clearInterval(poll)
      clearTimeout(flush)
      clearTimeout(reconnect)
    }
  }, [runId, live])

  if (runId && isLocalRun(runId)) return { snapshot: null, status: 'sample' }
  const current = loaded && loaded.runId === runId ? loaded : null
  return { snapshot: current?.snapshot ?? null, status: current?.status ?? 'loading' }
}
