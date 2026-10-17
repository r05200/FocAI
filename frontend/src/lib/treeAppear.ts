// When each tree node appears. A new node's edge is drawn from its parent once the parent is fully
// on screen, and the node pops in when the line reaches it. Siblings that arrive together draw at
// the same time; a whole tree arriving at once (opening a run that's already going) unfolds level
// by level from the root. Nodes that arrive later (event stream or polling) start from the moment they're first seen.
//
// Times are kept per node id and never recomputed, so a node that's already on screen doesn't
// replay or jump when the tree updates. CSS delays are relative to when a node was first seen,
// which is when its component mounts.

import type { TreeNode } from '../types'

export const EDGE_DRAW_MS = 900
export const NODE_POP_MS = 300
export const ROOT_POP_MS = 500

export interface Appearance {
  root: boolean
  seenAt: number // ms, when the node first showed up
  drawAt: number | null // ms, when its edge starts drawing (null for the root)
  popAt: number // ms, when the node starts popping in
}

export type AppearSchedule = ReadonlyMap<string, Appearance>

// Wall-clock time, kept out of components (the React compiler treats it as impure in render).
export function now(): number {
  return Date.now()
}

export function popMs(a: Appearance): number {
  return a.root ? ROOT_POP_MS : NODE_POP_MS
}

// CSS delays for a node's pop-in and its edge's draw (negative = already under way or finished).
export function popDelay(a: Appearance): number {
  return a.popAt - a.seenAt
}
export function drawDelay(a: Appearance): number {
  return (a.drawAt ?? a.seenAt) - a.seenAt
}

// Adds times for nodes not in `prev` (returns `prev` itself when there's nothing new). `rootAfterMs`
// delays a brand-new root, e.g. until the prompt bar has finished moving.
export function scheduleAppearance(
  nodes: readonly TreeNode[],
  prev: AppearSchedule,
  at: number,
  rootAfterMs = 0,
): AppearSchedule {
  const ids = new Set(nodes.map((n) => n.id))
  const fresh = nodes.filter((n) => !prev.has(n.id))
  if (fresh.length === 0) return prev

  const next = new Map(prev)
  // A root that replaces another (the stand-in swapped for the backend's) is already on screen.
  const oldRoot = [...prev.values()].find((a) => a.root)
  // Parents before children.
  const byDepth = [...fresh].sort((a, b) => a.depth - b.depth)
  for (const n of byDepth) {
    const parent = n.parent_id && ids.has(n.parent_id) ? next.get(n.parent_id) : undefined
    if (!parent) {
      const popAt = oldRoot ? oldRoot.popAt : at + rootAfterMs
      next.set(n.id, { root: true, seenAt: at, drawAt: null, popAt })
      continue
    }
    const drawAt = Math.max(at, parent.popAt + popMs(parent))
    next.set(n.id, { root: false, seenAt: at, drawAt, popAt: drawAt + EDGE_DRAW_MS })
  }
  return next
}
