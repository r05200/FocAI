import type { Run, TreeNode } from '../types'

// What a node is doing, as shown in its popup and as the dot by its label. Not the raw status:
// a finished node shows whether it was kept, and a node in progress shows its phase.
interface NodeState {
  label: string
  dot: string
}

export function nodeState(node: TreeNode, chosen: boolean): NodeState {
  if (node.type === 'conclusion') return { label: 'Conclusion', dot: 'bg-kind-paper' }
  if (node.status === 'parked') return { label: 'Parked', dot: 'bg-muted/50' }
  if (node.status === 'failed') return { label: 'Stopped', dot: 'bg-muted' }
  if (node.awaiting_choice) return { label: 'Waiting for your choice', dot: 'bg-kind-note' }
  if (chosen) return { label: 'Kept', dot: 'bg-kind-paper' }
  if (node.phase === 'synthesis') return { label: 'Judging', dot: 'bg-kind-paper' }
  if (node.status === 'running') {
    return { label: node.phase === 'experiment' ? 'Experiment' : 'Running', dot: 'bg-kind-paper' }
  }
  if (node.status === 'pending') return { label: node.revert_to ? 'Revert option' : 'Hypothesis', dot: 'bg-muted' }
  return { label: 'Complete', dot: 'bg-muted' }
}

// How a run is described, and in what colour. The backend's "failed" covers a run the user stopped,
// one that hit a limit and one that crashed; Run.end_reason says which (older runs don't have it,
// and then a "failed" one reads as stopped).
type RunEnd = { label: string; style: string }

export function runEnd(run: Run): RunEnd {
  if (run.status === 'running') return { label: run.paused ? 'Paused' : 'Running', style: 'text-kind-paper' }
  if (run.status === 'done') {
    return run.end_reason === 'limit' || hitLimit(run)
      ? { label: 'Limit reached', style: 'text-kind-note' }
      : { label: 'Done', style: 'text-rel-supports' }
  }
  if (run.end_reason === 'error') return { label: 'Failed', style: 'text-kind-correction' }
  if (run.end_reason === 'limit' || hitLimit(run)) return { label: 'Limit reached', style: 'text-kind-note' }
  return { label: 'Stopped', style: 'text-muted' }
}

// The run used its whole node budget.
const hitLimit = (run: Run) => run.caps.node_budget > 0 && run.totals.nodes_total >= run.caps.node_budget
