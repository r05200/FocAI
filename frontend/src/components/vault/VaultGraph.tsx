import { useMemo } from 'react'
import { usePalette } from '../../hooks/usePalette'
import { personSlot } from '../../lib/colors'
import { mostCentralId, toMindMap, type MapLink, type MapNode } from '../../lib/vaultGraphData'
import { makeCardSprite } from '../../lib/vaultSprites'
import { useVaultStore } from '../../store/vaultStore'
import type { VaultGraph as VaultGraphData } from '../../types'
import MindMap3D from './MindMap3D'

interface Props {
  graph: VaultGraphData
  people: string[]
  active: boolean
}

// The people's vault: cards coloured by owner, joined by relation links.
export default function VaultGraph({ graph, people, active }: Props) {
  const data = useMemo(() => toMindMap(graph), [graph])
  const person = useVaultStore((s) => s.person)
  const selectedId = useVaultStore((s) => s.selectedId)
  const select = useVaultStore((s) => s.select)
  const palette = usePalette()
  const focusId = useMemo(() => (person ? mostCentralId(graph) : null), [person, graph])

  const nodeObject = useMemo(
    () => (n: MapNode, selected: boolean) =>
      makeCardSprite(
        n.label,
        `${n.item.person} · ${n.item.kind} · ${n.item.tags.slice(0, 2).join(', ')}`,
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
      tooltip={(n) => ({ title: n.label, subtitle: `${n.item.person} · ${n.item.kind}` })}
      linkColor={(l) => palette.relation[l.edge.relation]}
    />
  )
}
