// Left-to-right layout for the run tree: depth sets the column, and a node's children are spaced
// evenly above and below its own row, so the middle child of an odd number lines up with it and
// the rest mirror each other. Siblings are spaced by the tallest of their subtrees, so a busy
// branch never runs into its neighbour. Positions are circle centres, with the root at (0, 0).
import type { TreeNode } from '../types'

const DEPTH_GAP = 240 // horizontal distance between depths
const SIBLING_GAP = 130 // vertical room per leaf

export function layoutTree(nodes: TreeNode[]): Map<string, { x: number; y: number }> {
  const ids = new Set(nodes.map((n) => n.id))
  const children = new Map<string | null, TreeNode[]>()
  for (const n of [...nodes].sort((a, b) => a.created_at - b.created_at)) {
    const key = n.parent_id && ids.has(n.parent_id) ? n.parent_id : null
    children.set(key, [...(children.get(key) ?? []), n])
  }

  // How much vertical room a subtree needs: a leaf one slot, a parent as many of its tallest
  // child's slots as it has children.
  const height = new Map<string, number>()
  const measure = (n: TreeNode): number => {
    const kids = children.get(n.id) ?? []
    const h = kids.length === 0 ? SIBLING_GAP : kids.length * Math.max(...kids.map(measure))
    height.set(n.id, h)
    return h
  }

  const out = new Map<string, { x: number; y: number }>()
  const place = (n: TreeNode, depth: number, y: number) => {
    out.set(n.id, { x: depth * DEPTH_GAP, y })
    const kids = children.get(n.id) ?? []
    const step = kids.length === 0 ? 0 : Math.max(...kids.map((k) => height.get(k.id)!))
    kids.forEach((k, i) => place(k, depth + 1, y + (i - (kids.length - 1) / 2) * step))
  }

  // The root's centre is always (0, 0), however the tree grows, so a view centred on it when the
  // tree opens stays put as branches arrive. Several roots (not expected) are stacked below it.
  let bottom: number | null = null
  for (const root of children.get(null) ?? []) {
    const h = measure(root)
    const y: number = bottom === null ? 0 : bottom + h / 2
    place(root, 0, y)
    bottom = y + h / 2
  }
  return out
}
