// Tidy left-to-right layout for the run tree: depth sets the column, leaves sit one under another,
// and each parent is centred beside its children. Positions are React Flow coordinates (top-left).
import type { TreeNode } from '../types'

export const DEPTH_GAP = 240 // horizontal distance between depths
export const SIBLING_GAP = 130 // vertical room per leaf

export function layoutTree(nodes: TreeNode[]): Map<string, { x: number; y: number }> {
  const children = new Map<string | null, TreeNode[]>()
  for (const n of [...nodes].sort((a, b) => a.created_at - b.created_at)) {
    const key = n.parent_id && nodes.some((m) => m.id === n.parent_id) ? n.parent_id : null
    children.set(key, [...(children.get(key) ?? []), n])
  }
  const out = new Map<string, { x: number; y: number }>()
  let nextLeaf = 0
  // Returns the subtree's centre y.
  const place = (n: TreeNode, depth: number): number => {
    const kids = children.get(n.id) ?? []
    const y = kids.length === 0 ? nextLeaf++ * SIBLING_GAP : kids.map((k) => place(k, depth + 1)).reduce((a, b) => a + b, 0) / kids.length
    out.set(n.id, { x: depth * DEPTH_GAP, y })
    return y
  }
  for (const root of children.get(null) ?? []) place(root, 0)
  return out
}
