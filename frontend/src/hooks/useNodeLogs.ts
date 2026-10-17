import { getNodeLogs } from '../api/client'
import { deriveNodeLogs } from '../lib/nodeLogs'
import type { LogEntry, TreeNode } from '../types'
import { usePolled } from './usePolled'

// Where the entries came from: the backend's own log, or rebuilt in the browser from the node's
// saved state.
export type LogSource = 'loading' | 'backend' | 'derived'

// A node's log (GET /runs/{id}/nodes/{node}/logs, proposed). Until the backend serves it, the log
// is rebuilt from what it already saves. Refetched while `live` (the node may still be working).
export function useNodeLogs(
  runId: string | null,
  node: TreeNode | null,
  { enabled, sample, live }: { enabled: boolean; sample: boolean; live: boolean },
): { entries: LogEntry[]; source: LogSource } {
  // Keyed per node (not per snapshot poll), so the node's updates don't refetch it.
  const nodeId = node?.id
  const key = enabled && runId && nodeId && !sample ? `${runId}/${nodeId}` : null
  // entries null: the backend has no log for it.
  const current = usePolled(
    key,
    () => getNodeLogs(runId!, nodeId!).then((entries): { entries: LogEntry[] | null } => ({ entries }), () => ({ entries: null })),
    live,
  )

  if (!node) return { entries: [], source: 'derived' }
  if (sample) return { entries: deriveNodeLogs(node), source: 'derived' }
  if (!current) return { entries: [], source: 'loading' }
  return current.entries ? { entries: current.entries, source: 'backend' } : { entries: deriveNodeLogs(node), source: 'derived' }
}
