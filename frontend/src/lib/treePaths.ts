import type { TreeNode } from '../types'

// The chosen path: nodes the post judge (or a person) kept, the conclusion, and every ancestor of
// those. Their edges are drawn solid blue and stay that way.
export function chosenIds(nodes: readonly TreeNode[]): Set<string> {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const chosen = new Set<string>()
  const kept = (n: TreeNode) =>
    n.type === 'conclusion' || (n.decision?.verdict === 'keep' && n.decision.stage !== 'pre' && n.status !== 'parked')
  for (const n of nodes) {
    if (!kept(n)) continue
    for (let cur: TreeNode | undefined = n; cur && !chosen.has(cur.id); cur = byId.get(cur.parent_id ?? '')) {
      chosen.add(cur.id)
    }
  }
  return chosen
}

// A branch still in play: not yet kept, parked or stopped. While the run is going these are shown
// faint, with a pulse travelling down the line to them every few seconds.
export function isCandidate(n: TreeNode, chosen: ReadonlySet<string>): boolean {
  return n.parent_id !== null && !chosen.has(n.id) && n.status !== 'parked' && n.status !== 'failed'
}

// Every node under `nodeId` (children, their children, ...).
export function descendantIds(nodes: readonly TreeNode[], nodeId: string): Set<string> {
  const out = new Set<string>()
  let frontier = [nodeId]
  while (frontier.length) {
    const next = nodes.filter((n) => n.parent_id !== null && frontier.includes(n.parent_id) && !out.has(n.id))
    for (const n of next) out.add(n.id)
    frontier = next.map((n) => n.id)
  }
  return out
}

// The tree with each concluded node's subtree replaced by its conclusion (`concluded`: node id ->
// the conclusion node under it).
export function withConclusions(nodes: readonly TreeNode[], concluded: ReadonlyMap<string, TreeNode>): TreeNode[] {
  let out = [...nodes]
  for (const [nodeId, conclusion] of concluded) {
    if (!out.some((n) => n.id === nodeId)) continue
    const drop = descendantIds(out, nodeId)
    out = [...out.filter((n) => !drop.has(n.id)), conclusion]
  }
  return out
}
