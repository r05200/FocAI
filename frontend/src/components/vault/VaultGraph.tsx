import { useMemo } from 'react'
import { usePalette } from '../../hooks/usePalette'
import { personSlot } from '../../lib/colors'
import { isViewOnly } from '../../lib/vaultAccess'
import { mostCentralId, toMindMap, type MapLink, type MapNode } from '../../lib/vaultGraphData'
import { makeCardSprite } from '../../lib/vaultSprites'
import { useVaultStore } from '../../store/vaultStore'
import type { VaultGraph as VaultGraphData } from '../../types'
import MindMap3D from './MindMap3D'
import { vaultName } from '../../lib/vaultName'

interface Props {
  graph: VaultGraphData
  people: string[]
  active: boolean
}

// The people's vault: cards coloured by owner, joined by relation links.
export default function VaultGraph({ graph, people, active }: Props) {
  // Cards the user moved keep their spot when the map is rebuilt (e.g. after adding a card). Read
  // from the store directly: moving a card must not rebuild the map and reshuffle the others.
  const data = useMemo(() => toMindMap(graph, useVaultStore.getState().positions), [graph])
  const moveCard = useVaultStore((s) => s.moveCard)
  const relayout = useVaultStore((s) => s.relayout)
  const person = useVaultStore((s) => s.person)
  const viewOnly = isViewOnly(person)
  const selectedId = useVaultStore((s) => s.selectedId)
  const select = useVaultStore((s) => s.select)
  const palette = usePalette()
  const focusId = useMemo(() => (person ? mostCentralId(graph) : null), [person, graph])

  const nodeObject = useMemo(
    () => (n: MapNode, selected: boolean) =>
      makeCardSprite(
        n.label,
        `${vaultName(n.item.person)} · ${n.item.kind} · ${n.item.tags.slice(0, 2).join(', ')}`,
        palette,
        personSlot(palette, people, n.item.person),
        selected,
      ),
    [palette, people],
  )

  return (
    <MindMap3D<MapNode, MapLink>
      data={data}
      active={active}
      // One person's vault opens on their best-connected card; the team vault on everyone's middle.
      focusId={focusId}
      resetKey={person ?? ''}
      selectedId={selectedId}
      onSelect={select}
      nodeObject={nodeObject}
      // PATCH /vault/items/{id}/position, once per drop (the card stays pinned where it landed).
      // POST /vault/layout/regenerate: re-arrange the automatic layout; moved cards keep their spot.
      // Neither in a view-only vault (the team's, or a teammate's): that would change their cards.
      onNodeMoved={viewOnly ? undefined : (id, position) => void moveCard(id, position)}
      onRelayout={viewOnly ? undefined : () => relayout().catch((err) => console.warn('Could not re-arrange:', err))}
      tooltip={(n) => ({ title: n.label, subtitle: `${vaultName(n.item.person)} · ${n.item.kind}` })}
      linkColor={(l) => palette.relation[l.edge.relation]}
      signals
    />
  )
}
