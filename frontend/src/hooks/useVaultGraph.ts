import { useMemo } from 'react'
import { fixtureVaultGraph } from '../fixtures'
import { useVaultStore } from '../store/vaultStore'
import type { VaultGraph } from '../types'

export interface VaultGraphState {
  graph: VaultGraph
  loading: boolean
  error: string | null
}

// Hard-coded to the fixture for now. To go live, fetch `GET /api/vault/graph?person=` (returns
// VaultGraph, same shape as the fixture; omit `person` for everyone) and return it here.
export function useVaultGraph(person: string | null): VaultGraphState {
  const added = useVaultStore((s) => s.addedItems)
  const graph = useMemo((): VaultGraph => {
    const all = [...fixtureVaultGraph.nodes, ...added]
    const nodes = person ? all.filter((n) => n.person === person) : all
    const ids = new Set(nodes.map((n) => n.id))
    const edges = fixtureVaultGraph.edges.filter((e) => ids.has(e.source) && ids.has(e.target))
    return { nodes, edges }
  }, [person, added])
  return { graph, loading: false, error: null }
}

// Everyone with a vault. The order also fixes each person's colour, so newly added vaults go on
// the end rather than being re-sorted in (which would recolour existing people).
// To go live: `GET /api/vault/people`.
export function useVaultPeople(): string[] {
  const added = useVaultStore((s) => s.addedPeople)
  return useMemo(() => {
    const base = [...new Set(fixtureVaultGraph.nodes.map((n) => n.person))].sort()
    return [...base, ...added.filter((p) => !base.includes(p))]
  }, [added])
}
