import type { Run, TreeNode } from '../types'

// Small coloured dot per node status (popup header, tree labels).
export const STATUS_DOT: Record<TreeNode['status'], string> = {
  pending: 'bg-muted',
  running: 'bg-kind-paper',
  done: 'bg-rel-supports',
  parked: 'bg-muted/50',
  failed: 'bg-muted',
}

// What a node's status is called on screen. The backend's "failed" is a node the run was stopped
// on, so it reads as stopped.
const NODE_STATUS_LABEL: Record<TreeNode['status'], string> = {
  pending: 'Pending',
  running: 'Running',
  done: 'Done',
  parked: 'Parked',
  failed: 'Stopped',
}
export const nodeStatusLabel = (status: TreeNode['status']) => NODE_STATUS_LABEL[status]

// How a run is described, and in what colour. The backend's "failed" covers a run the user stopped
// (the usual case) and one that hit its node budget; a run that really crashed can't be told apart
// until the backend says why (see Run.end_reason in types.ts), so none is shown as an error.
export type RunEnd = { label: string; style: string }

export function runEnd(run: Run): RunEnd {
  if (run.status === 'running') return { label: run.paused ? 'Paused' : 'Running', style: 'text-kind-paper' }
  if (run.status === 'done') {
    return run.end_reason === 'limit' || hitLimit(run)
      ? { label: 'Limit reached', style: 'text-kind-note' }
      : { label: 'Done', style: 'text-rel-supports' }
  }
  if (run.end_reason === 'limit' || hitLimit(run)) return { label: 'Limit reached', style: 'text-kind-note' }
  return { label: 'Stopped', style: 'text-muted' }
}

// The run used its whole node budget.
const hitLimit = (run: Run) => run.caps.node_budget > 0 && run.totals.nodes_total >= run.caps.node_budget
