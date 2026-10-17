import { useMemo } from 'react'
import { fixtureVaultGraph } from '../fixtures'
import { useVaultStore, type RemoteStatus } from '../store/vaultStore'
import type { VaultGraph } from '../types'

export interface VaultGraphState {
  graph: VaultGraph
  status: RemoteStatus
}

// Cards and links for one person's vault, or everyone's when `person` is null. Comes from the
// backend (loaded once by the app shell); while it's unreachable, falls back to the sample data in
// src/fixtures plus whatever was added locally.
export function useVaultGraph(person: string | null): VaultGraphState {
  const { status, graph: remote } = useVaultStore((s) => s.remote)
  const addedItems = useVaultStore((s) => s.addedItems)
  const graph = useMemo((): VaultGraph => {
    const all =
      status === 'offline'
        ? { nodes: [...fixtureVaultGraph.nodes, ...addedItems], edges: fixtureVaultGraph.edges }
        : remote
    const nodes = person ? all.nodes.filter((n) => n.person === person) : all.nodes
    const ids = new Set(nodes.map((n) => n.id))
    return { nodes, edges: all.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) }
  }, [status, remote, addedItems, person])
  return { graph, status }
}

// Everyone with a vault, in first-seen order (that order fixes each person's colour).
export function useVaultPeople(): string[] {
  const status = useVaultStore((s) => s.remote.status)
  const vaults = useVaultStore((s) => s.remote.vaults)
  const order = useVaultStore((s) => s.peopleOrder)
  const added = useVaultStore((s) => s.addedPeople)
  return useMemo(() => {
    if (status === 'loading') return []
    const names =
      status === 'ok'
        ? vaults.map((v) => v.person)
        : [...new Set([...fixtureVaultGraph.nodes.map((n) => n.person).sort(), ...added])]
    // Known order first, then newcomers.
    return [...order.filter((p) => names.includes(p)), ...names.filter((p) => !order.includes(p))]
  }, [status, vaults, order, added])
}
