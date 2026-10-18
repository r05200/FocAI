import { ApiError, getNodeLogs, isOffline } from '../api/client'
import { deriveNodeLogs } from '../lib/nodeLogs'
import type { LogEntry, TreeNode } from '../types'
import { usePolled } from './usePolled'

// Where the entries came from: the backend's own log, or rebuilt in the browser from the node's
// saved state.
export type LogSource = 'loading' | 'backend' | 'derived'

// Fetched entries plus the ones that arrived live since, oldest first, each once.
function withLive(fetched: LogEntry[], live: LogEntry[]): LogEntry[] {
  if (live.length === 0) return fetched
  const ids = new Set(fetched.map((e) => e.id))
  return [...fetched, ...live.filter((e) => !ids.has(e.id))].sort((a, b) => a.ts - b.ts)
}

// A node's log (GET /runs/{id}/nodes/{node}/logs), with the lines that arrive live on the run's
// stream (node_log, `liveEntries`) added as they come. Refetched while `live` too, for when the
// stream isn't available. Without a backend log the entries are rebuilt from the node's state.
export function useNodeLogs(
  runId: string | null,
  node: TreeNode | null,
  { enabled, sample, live, liveEntries = [] }: { enabled: boolean; sample: boolean; live: boolean; liveEntries?: LogEntry[] },
): { entries: LogEntry[]; source: LogSource } {
  // Keyed per node (not per snapshot poll), so the node's updates don't refetch it.
  const nodeId = node?.id
  const key = enabled && runId && nodeId && !sample ? `${runId}/${nodeId}` : null
  // entries null: the backend has no log for it.
  const current = usePolled(
    key,
    () =>
      getNodeLogs(runId!, nodeId!).then(
        (entries): { entries: LogEntry[] | null } => ({ entries }),
        (err) => {
          // 404 (the saved snapshot lags the run, so a new node has no log yet) or no backend: no
          // log to show, rebuild one. Any other failure rejects, which keeps what was fetched before.
          if (isOffline(err) || (err instanceof ApiError && err.status === 404)) return { entries: null }
          throw err
        },
      ),
    live,
  )

  if (!node) return { entries: [], source: 'derived' }
  if (sample) return { entries: deriveNodeLogs(node), source: 'derived' }
  if (!current) return liveEntries.length ? { entries: liveEntries, source: 'backend' } : { entries: [], source: 'loading' }
  return current.entries
    ? { entries: withLive(current.entries, liveEntries), source: 'backend' }
    : { entries: withLive(deriveNodeLogs(node), liveEntries), source: 'derived' }
}
