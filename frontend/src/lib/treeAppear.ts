// Timing for the run tree's animations.
//
// Appearing: a node shows up as soon as the backend has it (faint while it's still undecided).
// The root waits for the prompt bar to land. The first real tree that arrives (opening an old run,
// or one already going) unfolds left to right instead: the line to each child is drawn from its
// parent once the parent has popped in (UNFOLD_DRAW_MS), then the child pops in, then the lines
// to its children, and so on.
//
// Pulses: while the run is going, a short blue dash travels down every undecided branch's line
// every PULSE_MS, taking PULSE_TRAVEL_MS, and the branch's circle ripples as it arrives. All
// pulses share one clock so they move together.
//
// Chosen: when a branch is kept, a solid blue line is drawn down its edge over CHOSEN_DRAW_MS and
// stays.
//
// Choices (manual mode): the lines to the proposals waiting on a person are drawn yellow, and each
// proposal's ring traces round once its line has arrived, then pulses. Picking one draws the blue
// line over the yellow, and the node turns blue as it arrives.
//
// Appearance times are kept per node id and never recomputed, so a node already on screen doesn't
// replay or jump when the tree updates. CSS delays are relative to when a node was first seen,
// which is when its component mounts.

import type { TreeNode } from '../types'

export const NODE_POP_MS = 300
const ROOT_POP_MS = 500
export const PULSE_MS = 5000
export const PULSE_TRAVEL_MS = 1000
export const CHOSEN_DRAW_MS = 1000
export const UNFOLD_DRAW_MS = 450

interface Appearance {
  root: boolean
  seenAt: number // ms, when the node first showed up
  drawAt: number | null // ms, when the line to it starts drawing (unfolding only)
  popAt: number // ms, when it starts popping in
}

export type AppearSchedule = ReadonlyMap<string, Appearance>

// Wall-clock time, kept out of components (the React compiler treats it as impure in render).
export function now(): number {
  return Date.now()
}

// CSS delay that puts a looping PULSE_MS animation in step with every other one, for an element
// mounting now.
export function pulsePhase(): number {
  return -(now() % PULSE_MS)
}

export function popMs(a: Appearance): number {
  return a.root ? ROOT_POP_MS : NODE_POP_MS
}

// CSS delay for a node's pop-in (negative = already under way or finished).
export function popDelay(a: Appearance): number {
  return a.popAt - a.seenAt
}

// CSS delay for drawing the line to a node, or null when it isn't drawn (it fades in instead).
export function drawDelay(a: Appearance): number | null {
  return a.drawAt === null ? null : a.drawAt - a.seenAt
}

// Manual mode's yellow line to a choice: when it starts drawing (wall clock) and for how long. It
// goes with the node's own appearance: drawn alongside its line while unfolding, else from when
// the node pops in, so nothing yellow shows before the node does.
export function choiceLine(a: Appearance): { at: number; ms: number; unfold: boolean } {
  return a.drawAt !== null
    ? { at: a.drawAt, ms: UNFOLD_DRAW_MS, unfold: true }
    : { at: a.popAt, ms: CHOSEN_DRAW_MS, unfold: false }
}

// Adds times for nodes not in `prev` (returns `prev` itself when there's nothing new). `rootAfterMs`
// delays a brand-new root, e.g. until the prompt bar has finished moving. `unfold`: these nodes
// unfold left to right (lines drawn level by level) instead of appearing straight away.
export function scheduleAppearance(
  nodes: readonly TreeNode[],
  prev: AppearSchedule,
  at: number,
  rootAfterMs = 0,
  unfold = false,
): AppearSchedule {
  const ids = new Set(nodes.map((n) => n.id))
  const fresh = nodes.filter((n) => !prev.has(n.id))
  if (fresh.length === 0) return prev

  const next = new Map(prev)
  // A root that replaces another (the stand-in swapped for the backend's) is already on screen.
  const oldRoot = [...prev.values()].find((a) => a.root)
  // Parents before children.
  for (const n of [...fresh].sort((a, b) => a.depth - b.depth)) {
    const parent = n.parent_id && ids.has(n.parent_id) ? next.get(n.parent_id) : undefined
    if (!parent) {
      next.set(n.id, { root: true, seenAt: at, drawAt: null, popAt: oldRoot ? oldRoot.popAt : at + rootAfterMs })
      continue
    }
    const parentDone = Math.max(at, parent.popAt + popMs(parent))
    next.set(
      n.id,
      unfold
        ? { root: false, seenAt: at, drawAt: parentDone, popAt: parentDone + UNFOLD_DRAW_MS }
        : { root: false, seenAt: at, drawAt: null, popAt: parentDone },
    )
  }
  return next
}
