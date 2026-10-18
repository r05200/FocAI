import type { Objective, TreeNode } from '../types'

// Where a run stands, for the root node's popup: how many of its objectives some finished node has
// advanced, and how its branches are doing.
export interface RunProgress {
  objectivesTotal: number
  objectivesMet: number
  branches: number
  done: number
  running: number
  parked: number
  pending: number
  stopped: number
}

// Branches are every node except the root and the conclusion (the answer, which is not work).
export function runProgress(nodes: readonly TreeNode[], objectives: readonly Objective[]): RunProgress {
  const branches = nodes.filter((n) => n.parent_id !== null && n.type !== 'conclusion')
  const count = (status: TreeNode['status']) => branches.filter((n) => n.status === status).length
  const met = metObjectives(nodes)
  return {
    objectivesTotal: objectives.length,
    objectivesMet: objectives.filter((o) => met.has(o.id)).length,
    branches: branches.length,
    done: count('done'),
    running: count('running'),
    parked: count('parked'),
    pending: count('pending'),
    stopped: count('failed'),
  }
}

// Objectives some finished node has advanced (by id).
export function metObjectives(nodes: readonly TreeNode[]): Set<string> {
  return new Set(nodes.filter((n) => n.status === 'done').flatMap((n) => n.criteria_progress))
}
