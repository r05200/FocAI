import { Background, ReactFlow, useNodesState, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useEffect } from 'react'
import { isTyping, useSpacePan } from '../../hooks/useSpacePan'
import { useUiStore, type TreeTool } from '../../store/uiStore'
import { CursorIcon, HandIcon } from '../ui/Icons'

// Delay before the root appears: the prompt bar's move to the top takes 1500ms (see RunTab).
const APPEAR_AFTER_MS = 1500

// The root of the run's tree, for now just a circle. Later: the real node card, status colours, etc.
function RootNode() {
  return (
    <div
      aria-label="Root"
      className="size-20 rounded-full border-2 border-fg bg-elev"
      style={{ animation: `node-pop 500ms var(--ease-zoom) ${APPEAR_AFTER_MS}ms both` }}
    />
  )
}

const nodeTypes = { root: RootNode }

// TODO: build these from the run's tree (RunSnapshot.nodes + node_created/node_updated events).
const initialNodes: Node[] = [{ id: 'root', type: 'root', position: { x: 0, y: 0 }, data: {} }]

const TOOLS: { tool: TreeTool; label: string; key: string; Icon: typeof CursorIcon }[] = [
  { tool: 'select', label: 'Select', key: 'V', Icon: CursorIcon },
  { tool: 'pan', label: 'Pan (hold Space)', key: 'H', Icon: HandIcon },
]

// React Flow canvas for the run's tree, with the same Select / Pan toolbar (and V, H and Space
// shortcuts) as the vault map, minus Move. Select: click or box-select nodes, drag a node to move
// it. Pan: drag anywhere to move the view. Scroll or pinch zooms; middle or right drag always pans.
export default function TreeCanvas({ active }: { active: boolean }) {
  // Controlled nodes need their change handler, or dragging a node has no effect.
  const [nodes, , onNodesChange] = useNodesState(initialNodes)
  const tool = useUiStore((s) => s.treeTool)
  const setTool = useUiStore((s) => s.setTreeTool)
  const spaceHeld = useSpacePan(active)
  const panning = tool === 'pan' || spaceHeld

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
        edges={[]}
        nodeTypes={nodeTypes}
        colorMode="system"
        fitView
        fitViewOptions={{ maxZoom: 1, padding: 0.5 }}
        panOnDrag={panning ? true : [1, 2]}
        selectionOnDrag={!panning}
        nodesDraggable={!panning}
        zoomOnScroll
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
      >
        <Background />
      </ReactFlow>

      {/* Same look and spot as the vault's toolbar (top centre of the working area). */}
      <div
        role="toolbar"
        aria-label="Tree tools"
        className="absolute top-3 left-1/2 flex -translate-x-1/2 gap-1 rounded-xl border border-line bg-elev p-1 shadow-lg shadow-black/20"
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
