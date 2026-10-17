import { Background, Handle, Position, ReactFlow, useNodesState, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, isOffline, parkNode } from '../../api/client'
import { isLocalRun } from '../../lib/localRun'
import { useNodeLogs } from '../../hooks/useNodeLogs'
import { useForks } from '../../hooks/useForks'
import { useRunTree } from '../../hooks/useRunTree'
import { isTyping, useSpacePan } from '../../hooks/useSpacePan'
import { STATUS_DOT } from '../../lib/nodeStatus'
import { drawDelay, now, popDelay, popMs, scheduleAppearance, type Appearance, type AppearSchedule } from '../../lib/treeAppear'
import { layoutTree } from '../../lib/treeLayout'
import type { TreeNode } from '../../types'
import { useUiStore, type TreeTool } from '../../store/uiStore'
import { CursorIcon, HandIcon, IdeasIcon } from '../ui/Icons'
import GrowEdge, { type GrowEdgeType } from './GrowEdge'
import NodeLogsPanel from './NodeLogsPanel'
import NodePanel from './NodePanel'

// Delay before the root appears: the prompt bar's move to the top takes 1500ms (see RunTab). Every
// other node follows it: its edge draws from the parent, then it pops in (lib/treeAppear).
const APPEAR_AFTER_MS = 1500

// How far past the furthest node on each side the view may be panned (flow units, i.e. before zoom).
const PAN_MARGIN = 512
// Zoom-out limit. React Flow's default is 0.5; zooming out now stops halfway to that (a 25%
// reduction instead of 50%), so the tree never shrinks to a speck.
const MIN_ZOOM = 0.75
const MAX_ZOOM = 2
// The toolbar appears once the prompt bar has finished moving to the top (RunTab: 1500ms).
const TOOLBAR_AFTER_MS = 1500

// popDelay / popMs: when (relative to mounting) and how long the node pops in.
type TreeNodeData = { node: TreeNode; isRoot: boolean; popDelay: number; popMs: number }
type FlowNode = Node<TreeNodeData, 'tree'>

const STATUS_RING: Record<TreeNode['status'], string> = {
  pending: 'border-line',
  running: 'border-kind-paper bg-kind-paper/25 animate-pulse',
  done: 'border-rel-supports',
  parked: 'border-line border-dashed opacity-60',
  failed: 'border-muted',
}

// A tree node: a circle (the root bigger) with a short label under it. Clicking it opens the node's popup. The tree grows left to right, so edges come in
// on the circle's left and leave on its right (the handles only anchor them).
function TreeNodeView({ data, selected }: NodeProps<FlowNode>) {
  const { node, isRoot, popDelay, popMs } = data
  // The pop-in scales the circle and label only: React Flow measures where the handles are when the
  // node mounts, so they must not be inside anything that's scaled down at that moment.
  const pop = { animation: `node-pop ${popMs}ms var(--ease-zoom) ${popDelay}ms both` }
  return (
    <div className="flex w-36 flex-col items-center">
      <div className="relative">
        <Handle type="target" position={Position.Left} className="!opacity-0" isConnectable={false} />
        <div
          aria-label={isRoot ? 'Root' : node.description}
          style={pop}
          className={`rounded-full border-2 bg-elev transition-shadow ${isRoot ? `size-20 ${node.status === 'running' ? STATUS_RING.running : 'border-fg'}` : `size-12 ${STATUS_RING[node.status]}`} ${
            selected ? 'ring-2 ring-fg ring-offset-2 ring-offset-bg' : ''
          }`}
        />
        <Handle type="source" position={Position.Right} className="!opacity-0" isConnectable={false} />
      </div>
      {isRoot && (
        <p style={pop} className="mt-2 text-center text-[11px] leading-snug font-medium text-muted">
          Research question
        </p>
      )}
      {!isRoot && (
        <p style={pop} className="mt-2 line-clamp-2 text-center text-[11px] leading-snug text-muted">
          <span className={`mr-1 inline-block size-1.5 rounded-full align-middle ${STATUS_DOT[node.status]}`} />
          {node.description}
        </p>
      )}
    </div>
  )
}

const edgeDelay = (a: Appearance | undefined) => (a ? drawDelay(a) : 0)

const nodeTypes = { tree: TreeNodeView }
const edgeTypes = { grow: GrowEdge }

// Until the backend has nodes for the run (or when it only exists in the browser), show a stand-in:
// the root, built from the question, and one pending branch to its right.
function placeholderTree(runId: string, question: string, startedAt: number): TreeNode[] {
  const base = {
    run_id: runId, type: 'hypothesis' as const, status: 'pending' as const, pre_score: null,
    post_score: null, decision: null, decided_by: null, result: null, criteria_progress: [],
    tokens: { agent: 0, scorer: 0, total: 0 }, usefulness_count: 0, person_scores: {},
  }
  return [
    { ...base, id: 'root', parent_id: null, depth: 0, description: question, created_at: startedAt },
    { ...base, id: 'placeholder', parent_id: 'root', depth: 1, description: 'Waiting for the agent’s first branch', created_at: startedAt + 0.001 },
  ]
}

const TOOLS: { tool: TreeTool; label: string; key: string; Icon: typeof CursorIcon }[] = [
  { tool: 'select', label: 'Select', key: 'V', Icon: CursorIcon },
  { tool: 'pan', label: 'Pan (hold Space)', key: 'H', Icon: HandIcon },
]

// React Flow canvas for the run's tree, with the same Select / Pan toolbar (and V, H and Space
// shortcuts) as the vault map, minus Move. Select: click or box-select nodes, drag a node to move
// it. Pan: drag anywhere to move the view. Scroll or pinch zooms; middle or right drag always pans.
interface Props {
  runId: string
  question: string
  startedAt: number // epoch seconds
  // The tab is on screen / the run is still going (keep polling for new nodes).
  active: boolean
  live: boolean
  onOpenRunVault: () => void
}

export default function TreeCanvas({ runId, question, startedAt, active, live, onOpenRunVault }: Props) {
  // The run's nodes from the backend: GET /runs/{id}, then its event stream while it's going (or
  // polling until the backend serves the stream). Without them the stand-in shows.
  const { snapshot, status } = useRunTree(runId, live && active)
  const hasNodes = (snapshot?.nodes.length ?? 0) > 0
  const forks = useForks(runId, hasNodes, live && active)
  // Nodes parked by hand here: shown parked straight away, whether or not the backend has taken it
  // (or can yet: POST .../park still answers 501).
  const [parkedByHand, setParkedByHand] = useState<ReadonlySet<string>>(new Set())
  const treeNodes = useMemo(() => {
    const nodes = snapshot && snapshot.nodes.length > 0 ? snapshot.nodes : placeholderTree(runId, question, startedAt)
    return parkedByHand.size === 0
      ? nodes
      : nodes.map((n) => (parkedByHand.has(n.id) ? { ...n, status: 'parked' as const } : n))
  }, [snapshot, runId, question, startedAt, parkedByHand])
  async function parkNodeByHand(nodeId: string) {
    if (!isLocalRun(runId)) {
      try {
        await parkNode(runId, nodeId)
      } catch (err) {
        // Not built yet (501) or no backend: park it here only. Any other refusal is shown.
        const unavailable = isOffline(err) || (err instanceof ApiError && err.status === 501)
        if (!unavailable) throw err
      }
    }
    setParkedByHand((s) => new Set(s).add(nodeId))
  }

  // When each node (and the edge into it) appears. Times are added for new nodes only, in render
  // so the first frame a node is on screen already has them.
  const [appear, setAppear] = useState<AppearSchedule>(() =>
    scheduleAppearance(treeNodes, new Map(), now(), APPEAR_AFTER_MS),
  )
  const [appearFor, setAppearFor] = useState(treeNodes)
  if (appearFor !== treeNodes) {
    setAppearFor(treeNodes)
    setAppear(scheduleAppearance(treeNodes, appear, now(), APPEAR_AFTER_MS))
  }

  // Laid out automatically; positions a person dragged are kept when new nodes arrive.
  const layoutNodes = useMemo((): FlowNode[] => {
    const pos = layoutTree(treeNodes)
    const has = (id: string | null) => !!id && treeNodes.some((m) => m.id === id)
    return treeNodes.map((n) => {
      const isRoot = !has(n.parent_id)
      const p = pos.get(n.id) ?? { x: 0, y: 0 }
      // The layout gives circle centres; React Flow wants the node box's top-left. The box is
      // 144px wide (w-36) with the circle centred at its top, so the root (80px) and a branch
      // (48px) line up on the same row.
      const r = isRoot ? 40 : 24
      const a = appear.get(n.id)
      return {
        id: n.id,
        type: 'tree',
        position: { x: p.x - 72, y: p.y - r },
        data: { node: n, isRoot, popDelay: a ? popDelay(a) : 0, popMs: a ? popMs(a) : 0 },
      }
    })
  }, [treeNodes, appear])
  // Controlled nodes need their change handler, or dragging a node has no effect.
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(layoutNodes)
  const [syncedWith, setSyncedWith] = useState(layoutNodes)
  if (syncedWith !== layoutNodes) {
    setSyncedWith(layoutNodes)
    setNodes((prev) =>
      layoutNodes.map((n) => {
        const old = prev.find((o) => o.id === n.id)
        return old ? { ...old, data: n.data } : n
      }),
    )
  }
  const edges = useMemo(
    (): GrowEdgeType[] =>
      treeNodes
        .filter((n) => n.parent_id && treeNodes.some((m) => m.id === n.parent_id))
        .map((n) => ({
          id: `${n.parent_id}-${n.id}`,
          source: n.parent_id!,
          target: n.id,
          type: 'grow',
          data: { drawDelay: edgeDelay(appear.get(n.id)) },
          style: n.status === 'parked' ? { strokeDasharray: '5 4', opacity: 0.5 } : undefined,
        })),
    [treeNodes, appear],
  )

  // Popup for the clicked node, and its logs sidebar.
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [logsOpen, setLogsOpen] = useState(false)
  const selected = treeNodes.find((n) => n.id === selectedId) ?? null
  const logs = useNodeLogs(runId, selected, {
    enabled: logsOpen,
    // The stand-in nodes don't exist on the backend: their log is rebuilt locally.
    sample: status === 'sample' || !hasNodes,
    live,
  })
  const tool = useUiStore((s) => s.treeTool)
  const setTool = useUiStore((s) => s.setTreeTool)
  const spaceHeld = useSpacePan(active)
  const panning = tool === 'pan' || spaceHeld

  const [toolbarShown, setToolbarShown] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setToolbarShown(true), TOOLBAR_AFTER_MS)
    return () => clearTimeout(t)
  }, [])

  // Panning is limited to the nodes' bounding box plus PAN_MARGIN on every side (nodes that haven't
  // been measured yet count as the root's 80px circle).
  const translateExtent = useMemo((): [[number, number], [number, number]] => {
    const xs = nodes.flatMap((n) => [n.position.x, n.position.x + (n.measured?.width ?? 80)])
    const ys = nodes.flatMap((n) => [n.position.y, n.position.y + (n.measured?.height ?? 80)])
    return [
      [Math.min(...xs) - PAN_MARGIN, Math.min(...ys) - PAN_MARGIN],
      [Math.max(...xs) + PAN_MARGIN, Math.max(...ys) + PAN_MARGIN],
    ]
  }, [nodes])

  // V / H switch tools, only while the Research tab is on screen. (Space = temporary pan.)
  useEffect(() => {
    if (!active) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'v' || e.key === 'V') setTool('select')
      else if (e.key === 'h' || e.key === 'H') setTool('pan')
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [active, setTool])

  return (
    <div className={`relative h-full ${panning ? 'cursor-grab active:cursor-grabbing' : ''}`}>
      <ReactFlow
        nodes={nodes}
        onNodesChange={onNodesChange}
        edges={edges}
        onNodeClick={(_, n) => setSelectedId(n.id)}
        onPaneClick={() => setSelectedId(null)}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        colorMode="system"
        fitView
        fitViewOptions={{ maxZoom: 1, padding: 0.5 }}
        panOnDrag={panning ? true : [1, 2]}
        selectionOnDrag={!panning}
        nodesDraggable={!panning}
        zoomOnScroll
        minZoom={MIN_ZOOM}
        maxZoom={MAX_ZOOM}
        translateExtent={translateExtent}
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
      >
        <Background />
      </ReactFlow>

      {/* Opens this run's vault (what the agent has discovered so far). Appears with the toolbar. */}
      <button
        aria-label="Run vault"
        title="Run vault: what the agent has found"
        inert={!toolbarShown}
        onClick={onOpenRunVault}
        className={`absolute top-3 right-5 grid size-9.5 place-items-center rounded-xl border border-line bg-elev text-muted shadow-lg shadow-black/20 transition-[opacity,color,background-color] duration-300 hover:bg-hover hover:text-fg ${
          toolbarShown ? 'opacity-100' : 'opacity-0'
        }`}
      >
        <IdeasIcon width={18} height={18} />
      </button>

      {selected && (
        <NodePanel
          key={selected.id}
          node={selected}
          forks={forks.filter((f) => f.node_id === selected.id)}
          onClose={() => {
            setSelectedId(null)
            setLogsOpen(false)
          }}
          onShowLogs={() => setLogsOpen(true)}
          logsOpen={logsOpen}
          isRoot={!treeNodes.some((m) => m.id === selected.parent_id)}
          onPark={() => parkNodeByHand(selected.id)}
        />
      )}
      <NodeLogsPanel
        open={logsOpen && !!selected}
        node={selected}
        entries={logs.entries}
        source={logs.source}
        onClose={() => setLogsOpen(false)}
      />

      {/* Same look and spot as the vault's toolbar (top centre of the working area). */}
      <div
        role="toolbar"
        aria-label="Tree tools"
        inert={!toolbarShown}
        className={`absolute top-3 left-1/2 flex -translate-x-1/2 gap-1 rounded-xl border border-line bg-elev p-1 shadow-lg shadow-black/20 transition-opacity duration-300 ${
          toolbarShown ? 'opacity-100' : 'opacity-0'
        }`}
      >
        {TOOLS.map(({ tool: t, label, key, Icon }) => {
          const on = t === 'pan' ? panning : !panning
          return (
            <button
              key={t}
              aria-label={label}
              aria-pressed={on}
              title={`${label} (${key})`}
              onClick={() => setTool(t)}
              className={`grid size-8 place-items-center rounded-lg transition-colors ${
                on ? 'bg-accent text-accent-fg' : 'text-muted hover:bg-hover hover:text-fg'
              }`}
            >
              <Icon />
            </button>
          )
        })}
      </div>
    </div>
  )
}
