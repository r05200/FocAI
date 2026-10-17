import { useMemo } from 'react'
import { SAMPLE_GRAPH, SAMPLE_PEOPLE } from '../fixtures/seed'
import { useVaultStore, type RemoteStatus } from '../store/vaultStore'
import type { VaultGraph } from '../types'

export interface VaultGraphState {
  graph: VaultGraph
  status: RemoteStatus
}

// Cards and links for one person's vault, or everyone's when `person` is null. The sample vaults
// (Alice and Bob, src/fixtures/seed.ts) are always included; on top of them come the backend's
// vaults (loaded once by the app shell), or, while it's unreachable, whatever was added locally.
export function useVaultGraph(person: string | null): VaultGraphState {
  const { status, graph: remote } = useVaultStore((s) => s.remote)
  const addedItems = useVaultStore((s) => s.addedItems)
  const graph = useMemo((): VaultGraph => {
    const live = status === 'ok' ? remote : { nodes: addedItems, edges: [] }
    const liveIds = new Set(live.nodes.map((n) => n.id))
    const all: VaultGraph = {
      nodes: [...SAMPLE_GRAPH.nodes.filter((n) => !liveIds.has(n.id)), ...live.nodes],
      edges: [...SAMPLE_GRAPH.edges, ...live.edges],
    }
    const nodes = person ? all.nodes.filter((n) => n.person === person) : all.nodes
    const ids = new Set(nodes.map((n) => n.id))
    return { nodes, edges: all.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) }
  }, [status, remote, addedItems, person])
  return { graph, status }
}

// Everyone with a vault, in first-seen order (that order fixes each person's colour): the sample
// people, then the backend's (or, offline, the locally added ones).
export function useVaultPeople(): string[] {
  const status = useVaultStore((s) => s.remote.status)
  const vaults = useVaultStore((s) => s.remote.vaults)
  const order = useVaultStore((s) => s.peopleOrder)
  const added = useVaultStore((s) => s.addedPeople)
  return useMemo(() => {
    const live = status === 'ok' ? vaults.map((v) => v.person) : added
    const names = [...new Set([...SAMPLE_PEOPLE, ...live])]
    // Known order first, then newcomers.
    return [...order.filter((p) => names.includes(p)), ...names.filter((p) => !order.includes(p))]
  }, [status, vaults, order, added])
}
