import { useMemo } from 'react'
import { usePalette } from '../../hooks/usePalette'
import { personSlot } from '../../lib/colors'
import { CARD_H, CARD_W, makeCardSprite } from '../../lib/vaultSprites'
import type { RunIdea } from '../../hooks/useRunVault'
import MindMap3D from '../vault/MindMap3D'

interface IdeaNode {
  id: string
  label: string
  idea: RunIdea
  // Starting position (the force layout refines it).
  x: number
  y: number
  z: number
}
type NoLink = { source: string; target: string }

const BRANCH_RING = 190 // distance of each branch's centre from the middle of the map
const GROUP_PULL = 0.08 // how hard ideas are pulled toward their branch centre
const GAP = { x: 16, y: 14 } // breathing room kept between neighbouring cards

// d3 force: pulls every idea toward its branch's anchor, so branches form tight clumps and the
// clumps spread around a ring. Ideas inside a clump still repel each other, so cards don't overlap.
function branchForce(anchors: Map<string, { x: number; y: number }>) {
  let nodes: { idea: RunIdea; x?: number; y?: number; vx?: number; vy?: number }[] = []
  const force = (alpha: number) => {
    for (const n of nodes) {
      const a = anchors.get(n.idea.branch)
      if (!a) continue
      n.vx = (n.vx ?? 0) + (a.x - (n.x ?? 0)) * GROUP_PULL * alpha
      n.vy = (n.vy ?? 0) + (a.y - (n.y ?? 0)) * GROUP_PULL * alpha
    }
  }
  force.initialize = (ns: typeof nodes) => {
    nodes = ns
  }
  return force
}

// d3 force: cards are wide rectangles, so round-node repulsion lets them overlap. This nudges any
// two overlapping cards apart along whichever axis needs the smaller move.
function cardCollide() {
  let nodes: { x?: number; y?: number; vx?: number; vy?: number }[] = []
  const force = () => {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i]
        const b = nodes[j]
        const dx = (b.x ?? 0) - (a.x ?? 0)
        const dy = (b.y ?? 0) - (a.y ?? 0)
        const ox = CARD_W + GAP.x - Math.abs(dx)
        const oy = CARD_H + GAP.y - Math.abs(dy)
        if (ox <= 0 || oy <= 0) continue
        if (ox < oy) {
          const s = ox * 0.7 * (dx >= 0 ? 1 : -1)
          a.vx = (a.vx ?? 0) - s
          b.vx = (b.vx ?? 0) + s
        } else {
          const s = oy * 0.7 * (dy >= 0 ? 1 : -1)
          a.vy = (a.vy ?? 0) - s
          b.vy = (b.vy ?? 0) + s
        }
      }
    }
  }
  force.initialize = (ns: typeof nodes) => {
    nodes = ns
  }
  return force
}

interface Props {
  ideas: RunIdea[]
  branches: string[]
  active: boolean
  selectedId: string | null
  onSelect: (id: string | null) => void
}

// The agent's own discoveries for the run: the same 3D map as the vault, but with no links.
// Ideas float in clumps, one clump per branch.
export default function RunVaultGraph({ ideas, branches, active, selectedId, onSelect }: Props) {
  // Each branch's centre, spread around a ring.
  const anchors = useMemo(
    () =>
      new Map(
        branches.map((b, i) => {
          const angle = (i / branches.length) * 2 * Math.PI - Math.PI / 2
          const r = branches.length > 1 ? BRANCH_RING : 0
          return [b, { x: Math.cos(angle) * r, y: Math.sin(angle) * r }] as const
        }),
      ),
    [branches],
  )

  // Start every idea stacked at its branch centre, flat (z = 0). Starting from random spots let
  // cards get stranded on the wrong side of another clump, or overlap at different depths.
  const data = useMemo(() => {
    const seen = new Map<string, number>()
    const sizes = new Map<string, number>()
    for (const i of ideas) sizes.set(i.branch, (sizes.get(i.branch) ?? 0) + 1)
    const nodes = ideas.map((idea): IdeaNode => {
      const k = seen.get(idea.branch) ?? 0
      seen.set(idea.branch, k + 1)
      const a = anchors.get(idea.branch) ?? { x: 0, y: 0 }
      const offset = (k - ((sizes.get(idea.branch) ?? 1) - 1) / 2) * (CARD_H + GAP.y)
      return { id: idea.id, label: idea.title, idea, x: a.x, y: a.y + offset, z: 0 }
    })
    return { nodes, links: [] as NoLink[] }
  }, [ideas, anchors])
  const palette = usePalette()

  const nodeObject = useMemo(
    () => (n: IdeaNode, selected: boolean) =>
      makeCardSprite(n.label, n.idea.branch, palette, personSlot(palette, branches, n.idea.branch), selected),
    [palette, branches],
  )

  const configureForces = useMemo(
    () => (g: { d3Force: (name: string, fn?: unknown) => unknown }) => {
      g.d3Force('branch', branchForce(anchors))
      g.d3Force('collide', cardCollide())
    },
    [anchors],
  )

  return (
    <MindMap3D<IdeaNode, NoLink>
      data={data}
      active={active}
      focusId={null}
      openWith="fit"
      selectedId={selectedId}
      onSelect={onSelect}
      nodeObject={nodeObject}
      tooltip={(n) => ({ title: n.label, subtitle: n.idea.branch })}
      configureForces={configureForces}
    />
  )
}
