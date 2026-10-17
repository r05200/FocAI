// Turns the backend VaultGraph into force-graph data: one node per vault item and one link per
// relation edge (contradicts / supports / ...). People aren't nodes; they're shown by colour.
import type { VaultEdge, VaultGraph, VaultItemView } from '../types'

export interface MapNode {
  id: string
  label: string
  item: VaultItemView
}

export interface MapLink {
  source: string
  target: string
  edge: VaultEdge
}

export function displayTitle(title: string) {
  return title.replace(/^\[fixture\]\s*/, '')
}

export function toMindMap(graph: VaultGraph): { nodes: MapNode[]; links: MapLink[] } {
  const ids = new Set(graph.nodes.map((n) => n.id))
  return {
    nodes: graph.nodes.map((item) => ({ id: item.id, label: displayTitle(item.title), item })),
    links: graph.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((edge) => ({ source: edge.source, target: edge.target, edge })),
  }
}

// The node the camera should open on: highest harmonic centrality (sum of 1/hop-distance to
// every other node), which works even when the graph has several disconnected clusters.
// Ties (e.g. no edges at all) go to the most-retrieved item.
export function mostCentralId(graph: VaultGraph): string | null {
  const adj = new Map(graph.nodes.map((n) => [n.id, [] as string[]]))
  for (const { source, target } of graph.edges) {
    adj.get(source)?.push(target)
    adj.get(target)?.push(source)
  }
  let best: VaultItemView | null = null
  let bestScore = -1
  for (const node of graph.nodes) {
    const dist = new Map([[node.id, 0]])
    const queue = [node.id]
    let score = 0
    for (let i = 0; i < queue.length; i++) {
      const d = dist.get(queue[i])! + 1
      for (const next of adj.get(queue[i])!) {
        if (dist.has(next)) continue
        dist.set(next, d)
        score += 1 / d
        queue.push(next)
      }
    }
    if (score > bestScore || (score === bestScore && best && node.retrieval_count > best.retrieval_count)) {
      bestScore = score
      best = node
    }
  }
  return best?.id ?? null
}
