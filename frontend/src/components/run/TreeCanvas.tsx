import { Background, Handle, Position, ReactFlow, useNodesState, type Node, type NodeChange, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, concludeNode, isOffline, nodeAction } from '../../api/client'
import { isLocalRun } from '../../lib/localRun'
import { metObjectives, runProgress } from '../../lib/runProgress'
import { useNodeLogs } from '../../hooks/useNodeLogs'
import { useAfter } from '../../hooks/useAfter'
import { useForks } from '../../hooks/useForks'
import { useRunTree } from '../../hooks/useRunTree'
import { isTyping, useSpacePan } from '../../hooks/useSpacePan'
import { nodeState } from '../../lib/nodeStatus'
import { CHOSEN_DRAW_MS, choiceLine, drawDelay, now, popDelay, popMs, PULSE_MS, pulsePhase, scheduleAppearance, type AppearSchedule } from '../../lib/treeAppear'
import { chosenIds, isCandidate, withConclusions } from '../../lib/treePaths'
import { layoutTree } from '../../lib/treeLayout'
import type { HumanAction, TreeNode } from '../../types'
import { useRunStore } from '../../store/runStore'
import { useUiStore, type TreeTool } from '../../store/uiStore'
import { BellIcon, CursorIcon, FileIcon, HandIcon, IdeasIcon, ResetViewIcon } from '../ui/Icons'
import TreeEdge, { type EdgeState, type TreeEdgeType } from './TreeEdge'
import ConclusionPanel from './ConclusionPanel'
import PatchPanel from './PatchPanel'
import { choiceNodes, pendingCount } from '../../lib/runInbox'
import RunCards, { InstructionList } from './RunCards'
import NodeLogsPanel from './NodeLogsPanel'
import NodePanel from './NodePanel'
import ObjectivesChecklist from './ObjectivesChecklist'

// Delay before the root appears: the prompt bar's move to the top takes 1500ms (see RunTab). Every
// other node follows it as soon as the backend has it (lib/treeAppear has the whole timing).
const APPEAR_AFTER_MS = 1500
// When the layout changes (a new child re-centres its siblings), nodes already on screen glide to
// their new spot (over 600ms) instead of jumping; the edges follow them.
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)

// How far past the furthest node on each side the view may be panned (flow units, i.e. before zoom).
const PAN_MARGIN = 2048
// Zoom-out limit. React Flow's default is 0.5; zooming out now stops halfway to that (a 25%
// reduction instead of 50%), so the tree never shrinks to a speck.
const MIN_ZOOM = 0.75
const MAX_ZOOM = 2
// The toolbar appears once the prompt bar has finished moving to the top (RunTab: 1500ms).
const TOOLBAR_AFTER_MS = 1500
// The notifications panel's width (it slides out from the right edge).
const INBOX_W = 340

// popDelay / popMs: when (relative to mounting) and how long the node pops in. chosen: on the
// chosen path. faint: still undecided. ripple: the run is going and the branch is still in play,
// so a pulse arrives at it every few seconds.
type TreeNodeData = {
  node: TreeNode
  isRoot: boolean
  popDelay: number
  popMs: number
  chosen: boolean
  faint: boolean
  ripple: boolean
  // Manual mode: this is one of the proposals the run waits on a person to choose between (a yellow
  // ring pulses round it). `choiceAt`: wall-clock ms when the yellow line into it starts drawing;
  // `ringAfterMs`: how long after that the ring starts tracing round (the line has arrived and the
  // node has popped in).
  choice: boolean
  choiceAt: number
  ringAfterMs: number
}
type FlowNode = Node<TreeNodeData, 'tree'>

const STATUS_RING: Record<TreeNode['status'], string> = {
  pending: 'border-line',
  running: 'border-kind-paper bg-kind-paper/25 animate-pulse',
  done: 'border-line', // finished but not (yet) kept; kept ones are blue
  parked: 'border-line border-dashed opacity-60',
  failed: 'border-muted',
}

// A tree node: a circle (the root bigger) with a short label under it. Clicking it opens the
// node's popup. The tree grows left to right, so edges come in on the circle's left and leave on its
// right (the handles only anchor them).
function TreeNodeView({ data, selected }: NodeProps<FlowNode>) {
  const { node, isRoot, popDelay, popMs, chosen, faint, ripple, choice, choiceAt, ringAfterMs } = data
  // Once a choice, its yellow ring stays to hand over: picked, it waits for the blue line to arrive
  // (and the circle turns blue then); dropped, it fades at once.
  const [wasChoice, setWasChoice] = useState(choice)
  if (choice && !wasChoice) setWasChoice(true)
  const picked = wasChoice && !choice && chosen
  const ring = isRoot
    ? node.status === 'running' ? STATUS_RING.running : 'border-fg'
    : chosen ? 'border-kind-paper' : STATUS_RING[node.status]
  // The pop-in scales the circle and label only: React Flow measures where the handles are when the
  // node mounts, so they must not be inside anything that's scaled down at that moment.
  const pop = {
    animation: `node-pop ${popMs}ms var(--ease-zoom) ${popDelay}ms both`,
    ...(picked ? { transition: `border-color 300ms ease-out ${CHOSEN_DRAW_MS}ms` } : {}),
  }
  return (
    // Faintness is on the wrapper: the pop-in animation owns the circle's own opacity.
    <div className={`flex w-36 flex-col items-center transition-opacity duration-500 ${faint ? 'opacity-45' : ''}`}>
      <div className="relative">
        {ripple && <Ripple afterMs={popDelay + popMs} />}
        {wasChoice && <ChoiceRing at={choiceAt} afterMs={ringAfterMs} ending={choice ? null : picked ? CHOSEN_DRAW_MS : 0} />}
        <Handle type="target" position={Position.Left} className="opacity-0!" isConnectable={false} />
        <div
          aria-label={isRoot ? 'Root' : node.description}
          style={pop}
          className={`relative grid place-items-center rounded-full border-2 bg-elev text-muted transition-[box-shadow,border-color] ${isRoot ? 'size-20' : 'size-12'} ${ring} ${
            selected ? 'ring-2 ring-fg ring-offset-2 ring-offset-bg' : ''
          }`}
        >
          {/* A revert option: going back to an earlier node's code is one of the choices. */}
          {node.revert_to && <UndoIcon />}
        </div>
        <Handle type="source" position={Position.Right} className="opacity-0!" isConnectable={false} />
      </div>
      {isRoot && (
        <p style={pop} className="mt-2 text-center text-[11px] leading-snug font-medium text-muted">
          Research question
        </p>
      )}
      {!isRoot && (
        <p style={pop} className="mt-2 line-clamp-2 text-center text-[11px] leading-snug text-muted">
          <span className={`mr-1 inline-block size-1.5 rounded-full align-middle ${nodeState(node, chosen).dot}`} />
          {node.description}
        </p>
      )}
    </div>
  )
}

// The blue ring that spreads out from a branch as a pulse reaches it (in step with the pulse on
// its line: both run on the shared PULSE_MS clock).
// It waits until the node has finished popping in (`afterMs` from now).
function Ripple({ afterMs }: { afterMs: number }) {
  const [phase] = useState(pulsePhase)
  const ready = useAfter(afterMs)
  if (!ready) return null
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 rounded-full border-2 border-kind-paper"
      style={{ animation: `node-ripple ${PULSE_MS}ms ease-out ${phase}ms infinite` }}
    />
  )
}

// How far an element sits from the top of the page, ignoring transforms (the tab switch scales the
// whole view while it animates, which would throw getBoundingClientRect off).
function pageTop(el: HTMLElement): number {
  let top = 0
  for (let e: HTMLElement | null = el; e; e = e.offsetParent as HTMLElement | null) top += e.offsetTop
  return top
}

// The conclusion drawn the moment Conclude is pressed, until the backend's own arrives.
function localConclusion(node: TreeNode): TreeNode {
  return {
    id: `conclusion_${node.id}`,
    run_id: node.run_id,
    parent_id: node.id,
    depth: node.depth + 1,
    type: 'conclusion',
    status: 'done',
    phase: 'complete',
    description: `Conclusion: ${node.description}`,
    pre_score: null,
    post_score: null,
    decision: null,
    decided_by: 'human',
    result: null,
    criteria_progress: [],
    tokens: { agent: 0, scorer: 0, total: 0 },
    usefulness_count: 0,
    person_scores: {},
    created_at: now() / 1000,
  }
}

// A keep / park / restore made without a backend, as the node would show it.
function withLocalAction(n: TreeNode, action: HumanAction | undefined): TreeNode {
  if (action === 'park') return { ...n, status: 'parked' }
  if (action === 'restore' || action === 'keep') {
    return {
      ...n,
      status: n.status === 'parked' ? 'pending' : n.status,
      decision: action === 'keep' ? { verdict: 'keep', stage: 'human', reason: 'Kept by hand.', vault_items_used: [] } : null,
    }
  }
  return n
}

// Manual mode's choice: a yellow ring traces once round the circle from the top, `afterMs` after the
// yellow line into the node starts drawing (wall clock `at`; at once if that's past), then pulses
// until the choice is made. `ending`: the choice is over; the ring fades out after that many ms.
function ChoiceRing({ at, afterMs, ending }: { at: number; afterMs: number; ending: number | null }) {
  const [delay] = useState(() => Math.max(0, at - now()) + afterMs)
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 100"
      className="pointer-events-none absolute -inset-1.5 size-[calc(100%+12px)] -rotate-90 overflow-visible"
    >
      <circle
        cx={50}
        cy={50}
        r={48}
        fill="none"
        stroke="var(--color-kind-note)"
        strokeWidth={2.5}
        vectorEffect="non-scaling-stroke"
        pathLength={1}
        strokeDasharray="1"
        style={{
          animation:
            ending === null
              ? `edge-draw ${RING_TRACE_MS}ms var(--ease-zoom) ${delay}ms both, ring-pulse 2000ms ease-in-out ${delay + RING_TRACE_MS}ms infinite`
              : `fade-out 300ms ease-out ${ending}ms both`,
        }}
      />
    </svg>
  )
}
const RING_TRACE_MS = 800

function UndoIcon() {
  return (
    <svg aria-label="Revert" width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 14 4 9l5-5" />
      <path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" />
    </svg>
  )
}

const nodeTypes = { tree: TreeNodeView }
const edgeTypes = { tree: TreeEdge }

// Until the backend has nodes for the run, the root alone, built from the question. When there's no
// answer from the backend at all (unreachable, or the run only exists in the browser) a pending
// branch is drawn to its right as well, so there's still something to look at.
function placeholderTree(runId: string, question: string, startedAt: number, withBranch: boolean): TreeNode[] {
  const base = {
    run_id: runId, type: 'hypothesis' as const, status: 'pending' as const, pre_score: null,
    post_score: null, decision: null, decided_by: null, result: null, criteria_progress: [],
    tokens: { agent: 0, scorer: 0, total: 0 }, usefulness_count: 0, person_scores: {},
  }
  const root: TreeNode = { ...base, id: 'root', parent_id: null, depth: 0, description: question, created_at: startedAt }
  if (!withBranch) return [root]
  return [
    root,
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
  // The prompt bar is still moving: the pulses and ripples wait until it has landed.
  hold?: boolean
  onOpenRunVault: () => void
  onDebugReload: () => void // DEBUG ONLY, see the reload button below
}

// TODO(REMOVE BEFORE SHIPPING): the whole "reload" debugging aid: this wrapper, `onDebugReload` and
// the reload button in the tree below. It remounts the tree so it fetches and draws itself again
// from scratch (the same as reopening the run), for checking the draw animation and layout.
export default function TreeCanvas(props: Omit<Props, 'onDebugReload'>) {
  const [reloads, setReloads] = useState(0)
  return <TreeCanvasView key={reloads} {...props} onDebugReload={() => setReloads((n) => n + 1)} />
}

function TreeCanvasView({ runId, question, startedAt, active, live, hold = false, onOpenRunVault, onDebugReload }: Props) {
  const pulses = live && !hold
  // The run's nodes from the backend: GET /runs/{id}, then its event stream while it's going (or
  // polling until the backend serves the stream). Without them the stand-in shows.
  // `live`, not `live && active`: the stream and the state built on it must outlive a tab switch.
  const { snapshot, status, logs: liveLogs, forks: liveForks, apply } = useRunTree(runId, live)
  const hasNodes = (snapshot?.nodes.length ?? 0) > 0
  const polledForks = useForks(runId, hasNodes, live && active)
  // Forks: the polled list, with the live / just-returned versions laid over it.
  const forks = useMemo(() => {
    const byId = new Map(polledForks.map((f) => [f.id, f]))
    for (const [id, f] of liveForks) byId.set(id, f)
    return [...byId.values()].sort((a, b) => a.created_at - b.created_at)
  }, [polledForks, liveForks])
  // The fork waiting for a decision blocks the run (nothing new starts) and a person's node actions
  // (the backend refuses them with 409 until it's confirmed or dismissed).
  const pendingFork =
    forks.find((f) => f.status === 'requested' && f.id === snapshot?.run.fork_id) ??
    (snapshot?.run.awaiting === 'fork' ? (forks.find((f) => f.status === 'requested') ?? null) : null)
  const lastFork = [...forks].reverse().find((f) => f.status === 'confirmed') ?? null
  const canAct = live && !pendingFork
  // The run's command state, for the notice under the prompt bar (which can't see the snapshot).
  const setCommandState = useRunStore((s) => s.setCommandState)
  const viewedRun = snapshot?.run
  const commandQuestion = live
    ? (snapshot?.questions.find((q) => q.purpose === 'command' && q.status === 'pending') ?? null)
    : null
  useEffect(() => {
    if (!viewedRun) return
    setCommandState({
      runId,
      plan: viewedRun.plan ?? null,
      commandKnown: !!viewedRun.command,
      hasFiles: (viewedRun.paths?.length ?? 0) > 0,
      question: viewedRun.awaiting === 'command' ? commandQuestion : null,
    })
  }, [runId, viewedRun, commandQuestion, setCommandState])
  useEffect(
    () => () => {
      if (useRunStore.getState().commandState?.runId === runId) setCommandState(null)
    },
    [runId, setCommandState],
  )
  // Keep / park / restore done here while there's no backend to take them (a run that only exists
  // in the browser, or the backend unreachable): shown on the node all the same.
  const [localActions, setLocalActions] = useState<ReadonlyMap<string, HumanAction>>(new Map())
  // Nodes concluded here (node id -> its conclusion): the subtree under each is replaced by the
  // conclusion as soon as Conclude is pressed, then by what the backend returns.
  const [concluded, setConcluded] = useState<ReadonlyMap<string, TreeNode>>(new Map())
  const treeNodes = useMemo(() => {
    const nodes = snapshot && snapshot.nodes.length > 0 ? snapshot.nodes : placeholderTree(runId, question, startedAt, status === 'sample')
    const acted = localActions.size === 0 ? nodes : nodes.map((n) => withLocalAction(n, localActions.get(n.id)))
    return concluded.size === 0 ? acted : withConclusions(acted, concluded)
  }, [snapshot, status, runId, question, startedAt, localActions, concluded])
  // POST .../nodes/{id}/keep | park | restore. The node the backend returns goes on screen at once
  // (the stream or next poll confirms it); a refusal (409: the run finished, or the action doesn't
  // fit) is thrown for the popup to show.
  async function actOnNode(nodeId: string, action: HumanAction) {
    if (!isLocalRun(runId)) {
      try {
        const node = await nodeAction(runId, nodeId, action)
        apply((o) => o.nodes.set(node.id, node))
        return
      } catch (err) {
        if (!isOffline(err)) throw err
      }
    }
    setLocalActions((m) => new Map(m).set(nodeId, action))
  }

  // Conclude at a node: its children (and everything under them) give way to a conclusion node,
  // drawn at once; then POST .../nodes/{id}/conclude, whose conclusion replaces the stand-in. If
  // the route isn't there yet (or no backend) the stand-in stays; a refusal puts the tree back.
  async function concludeAt(node: TreeNode) {
    const standIn = localConclusion(node)
    setConcluded((m) => new Map(m).set(node.id, standIn))
    if (isLocalRun(runId)) return
    try {
      const conclusion = await concludeNode(runId, node.id)
      if (conclusion?.type === 'conclusion') setConcluded((m) => new Map(m).set(node.id, conclusion))
    } catch (err) {
      const notThere =
        isOffline(err) || (err instanceof ApiError && (err.status === 404 || err.status === 405 || err.status === 501))
      if (notThere) return
      setConcluded((m) => {
        const next = new Map(m)
        next.delete(node.id)
        return next
      })
      throw err
    }
  }

  // When each node (and the edge into it) appears. Times are added for new nodes only, in render
  // so the first frame a node is on screen already has them.
  const [appear, setAppear] = useState<AppearSchedule>(() =>
    scheduleAppearance(treeNodes, new Map(), now(), APPEAR_AFTER_MS),
  )
  const [appearFor, setAppearFor] = useState(treeNodes)
  // The first real tree from the backend unfolds left to right; anything after that appears as it
  // comes (the stand-in shown until then doesn't count).
  const [unfolded, setUnfolded] = useState(false)
  if (appearFor !== treeNodes) {
    setAppearFor(treeNodes)
    setAppear(scheduleAppearance(treeNodes, appear, now(), APPEAR_AFTER_MS, hasNodes && !unfolded))
    if (hasNodes && !unfolded) setUnfolded(true)
  }

  const chosen = useMemo(() => chosenIds(treeNodes), [treeNodes])
  // Manual mode: the proposals the run waits on a choice between (yellow, until one is picked).
  const choices = useMemo(() => new Set(choiceNodes(treeNodes).map((n) => n.id)), [treeNodes])

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
      const choice = choices.has(n.id)
      const line = a ? choiceLine(a) : { at: 0, ms: CHOSEN_DRAW_MS, unfold: false }
      return {
        id: n.id,
        type: 'tree',
        position: { x: p.x - 72, y: p.y - r },
        data: {
          node: n,
          isRoot,
          popDelay: a ? popDelay(a) : 0,
          popMs: a ? popMs(a) : 0,
          chosen: chosen.has(n.id),
          faint: !isRoot && !choice && isCandidate(n, chosen) && n.status !== 'running',
          ripple: pulses && !isRoot && !choice && isCandidate(n, chosen),
          choice,
          choiceAt: line.at,
          // Unfolding, the node pops in once its line is drawn: the ring waits for that too.
          ringAfterMs: line.ms + (line.unfold && a ? popMs(a) : 0),
        },
      }
    })
  }, [treeNodes, appear, chosen, choices, pulses])
  // Controlled nodes need their change handler, or dragging a node has no effect.
  const [nodes, setNodes, applyNodeChanges] = useNodesState<FlowNode>(layoutNodes)
  // Nodes a person dragged keep their spot; every other node follows the layout as the tree grows
  // (adding a child re-centres its parent's other children).
  const [dragged, setDragged] = useState<ReadonlySet<string>>(new Set())
  function onNodesChange(changes: NodeChange<FlowNode>[]) {
    // Selecting one node any way (a click, or the keyboard: Tab to it, Enter) opens its popup.
    const picked = changes.filter((c) => c.type === 'select' && c.selected)
    if (picked.length === 1) setSelectedId((picked[0] as { id: string }).id)
    const moved = changes.filter((c) => c.type === 'position' && c.dragging).map((c) => (c as { id: string }).id)
    if (moved.some((id) => !dragged.has(id))) setDragged((s) => new Set([...s, ...moved]))
    applyNodeChanges(changes)
  }
  // New nodes go straight to their spot (they pop in there); nodes already on screen keep where they
  // are for now and glide to the layout's spot in the effect below.
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
  const draggedNow = useRef(dragged)
  useEffect(() => {
    draggedNow.current = dragged
  }, [dragged])
  useEffect(() => {
    const target = new Map(layoutNodes.map((n) => [n.id, n.position]))
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    // Where each moving node starts: read from the nodes as they are on the first frame (mid-glide
    // if the layout changed again before the last glide ended, so it carries on from there).
    let from: Map<string, { x: number; y: number }> | null = null
    let start = 0
    let frame = 0
    let moving = true
    const step = (time: number) => {
      start ||= time
      const k = reduced ? 1 : easeInOut(Math.min(1, (time - start) / 600))
      setNodes((prev) => {
        from ??= new Map(prev.map((n) => [n.id, n.position]))
        const begun = from
        let changed = false
        const next = prev.map((n) => {
          const to = target.get(n.id)
          const a = begun.get(n.id)
          if (!to || !a || draggedNow.current.has(n.id)) return n
          if (n.position.x === to.x && n.position.y === to.y) return n
          changed = true
          return { ...n, position: { x: a.x + (to.x - a.x) * k, y: a.y + (to.y - a.y) * k } }
        })
        moving = changed
        // Nothing to move (only the nodes' data changed): keep the same array, so no re-render.
        return changed ? next : prev
      })
      if (k < 1 && moving) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [layoutNodes, setNodes])
  const edges = useMemo(
    (): TreeEdgeType[] =>
      treeNodes
        .filter((n) => n.parent_id && treeNodes.some((m) => m.id === n.parent_id))
        .map((n): TreeEdgeType => {
          const a = appear.get(n.id)
          const state: EdgeState = chosen.has(n.id)
            ? 'chosen'
            : n.status === 'parked' ? 'parked' : n.status === 'failed' ? 'stopped' : 'candidate'
          const choice = choices.has(n.id)
          const line = a ? choiceLine(a) : { at: 0, ms: CHOSEN_DRAW_MS }
          return {
            id: `${n.parent_id}-${n.id}`,
            source: n.parent_id!,
            target: n.id,
            type: 'tree',
            // The chosen path's blue line is drawn over the dashed and faint ones where they share a stretch.
            data: {
              state,
              appearDelay: a ? popDelay(a) : 0,
              drawDelay: a ? drawDelay(a) : null,
              pulsing: pulses,
              choice,
              choiceAt: line.at,
              choiceMs: line.ms,
            },
            // The yellow line to a choice goes over everything else.
            zIndex: choice ? 11 : state === 'chosen' ? 10 : 0,
          }
        })
        .concat(
          // A conclusion also gets a line from every node it draws on (supported or not), so its
          // sources fan into it; the line from its parent is the tree edge above.
          treeNodes
            .filter((n) => n.type === 'conclusion')
            .flatMap((n) => {
              const a = appear.get(n.id)
              return (n.combines ?? [])
                .filter((id) => id !== n.parent_id)
                .map((id) => treeNodes.find((m) => m.id === id))
                .filter((m): m is TreeNode => !!m)
                .map((m): TreeEdgeType => ({
                  id: `source-${m.id}-${n.id}`,
                  source: m.id,
                  target: n.id,
                  type: 'tree',
                  data: {
                    state: m.status === 'parked' ? 'parked' : 'stopped',
                    appearDelay: a ? popDelay(a) : 0,
                    drawDelay: a ? drawDelay(a) : null,
                    pulsing: false,
                  },
                  zIndex: 0,
                }))
            }),
        ),
    [treeNodes, appear, chosen, choices, pulses],
  )

  // Popup for the clicked node, and its logs sidebar.
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // One sidebar at a time: the node's logs, or (on the conclusion node) the conclusion.
  const [logsOpen, setLogsOpen] = useState(false)
  const [conclusionOpen, setConclusionOpen] = useState(false)
  // The run's changes to the user's files (GET /runs/{id}/patch), once it has them.
  const [patchOpen, setPatchOpen] = useState(false)
  const patchReady = !!snapshot?.run.patch_ready
  // Manual mode's switch lives by the prompt bar (RunTab): it's told what the run says, and the run
  // the backend returns on a flip (awaiting "choice" or not) goes on screen here at once.
  const setServerManual = useRunStore((s) => s.setServerManual)
  const serverManual = snapshot?.run.manual
  useEffect(() => {
    if (serverManual !== undefined) setServerManual(runId, serverManual)
  }, [runId, serverManual, setServerManual])
  const manualReply = useRunStore((s) => s.manualReply)
  useEffect(() => {
    if (manualReply?.id !== runId) return
    apply((o) => (o.run = manualReply))
    useRunStore.setState({ manualReply: null })
  }, [manualReply, runId, apply])
  // The notifications panel (the bell, top right) and how many things wait on a person.
  const [inboxOpen, setInboxOpen] = useState(false)
  const waitingCount = snapshot ? pendingCount(treeNodes, snapshot.suggestions ?? [], pendingFork) : 0
  const selected = treeNodes.find((n) => n.id === selectedId) ?? null
  const logs = useNodeLogs(runId, selected, {
    enabled: logsOpen,
    liveEntries: selected ? liveLogs.get(selected.id) : undefined,
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

  const area = useRef<HTMLDivElement>(null)

  // The node card's default spot is just below the top-right corner's buttons and checklist.
  const corner = useRef<HTMLDivElement>(null)
  const [cornerBottom, setCornerBottom] = useState(64)
  const [cornerWidth, setCornerWidth] = useState(0)
  useEffect(() => {
    const el = corner.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setCornerBottom(el.offsetTop + el.offsetHeight + 12)
      setCornerWidth(el.offsetWidth)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    // The tree and its side panel (logs or conclusion) share the row: opening one narrows the tree.
    <div className="flex h-full">
    <div ref={area} className={`relative min-w-0 flex-1 overflow-hidden ${panning ? 'cursor-grab active:cursor-grabbing' : ''}`}>
      <ReactFlow
        nodes={nodes}
        onNodesChange={onNodesChange}
        edges={edges}
        onNodeClick={(_, n) => {
          setSelectedId(n.id)
          setConclusionOpen(false)
        }}
        onPaneClick={() => {
          setSelectedId(null)
          setLogsOpen(false)
          setConclusionOpen(false)
        }}
        // Backspace would delete the selected node from the canvas (the tree isn't editable).
        deleteKeyCode={null}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        colorMode="system"
        // Opens on the root: centred across the tree area, and halfway down the screen (not the
        // area, which starts below the prompt bar). The layout keeps the root at (0, 0).
        onInit={(flow) => {
          const el = area.current
          if (!el) return
          void flow.setViewport({ x: el.clientWidth / 2, y: window.innerHeight / 2 - pageTop(el), zoom: 1 })
        }}
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

      {/* Top-right corner, appearing with the toolbar: the reload (debug), run vault, changes and
          notifications buttons. They move aside with the notifications panel, like the objectives. */}
      <div
        ref={corner}
        inert={!toolbarShown}
        style={{ right: inboxOpen ? INBOX_W + 20 : 20 }}
        className={`absolute top-3 z-20 flex items-start gap-2.5 transition-[right,opacity] duration-300 ease-zoom ${
          toolbarShown ? 'opacity-100' : 'opacity-0'
        }`}
      >
        {/* TODO(REMOVE BEFORE SHIPPING): debugging only. Redraws the tree from scratch. */}
        <button
          aria-label="Reload tree (debug)"
          title="Reload tree (debug only, remove before shipping)"
          onClick={onDebugReload}
          className="grid size-9.5 shrink-0 place-items-center rounded-xl border border-dashed border-kind-note bg-elev text-kind-note shadow-lg shadow-black/20 transition-colors hover:bg-hover"
        >
          <ResetViewIcon width={18} height={18} />
        </button>

        {/* Opens this run's vault (what the agent has discovered so far). */}
        <button
          aria-label="Run vault"
          title="Run vault: what the agent has found"
          onClick={onOpenRunVault}
          className="grid size-9.5 shrink-0 place-items-center rounded-xl border border-line bg-elev text-muted shadow-lg shadow-black/20 transition-colors hover:bg-hover hover:text-fg"
        >
          <IdeasIcon width={18} height={18} />
        </button>

        {/* The changes the run left applied to the user's files, once it has finished with them. */}
        {patchReady && (
          <button
            aria-label="Changes to your files"
            title="Changes the run made to your files"
            aria-pressed={patchOpen}
            onClick={() => {
              setLogsOpen(false)
              setConclusionOpen(false)
              setPatchOpen((o) => !o)
            }}
            className={`grid size-9.5 shrink-0 place-items-center rounded-xl border bg-elev shadow-lg shadow-black/20 transition-colors hover:bg-hover hover:text-fg ${
              patchOpen ? 'border-fg text-fg' : 'border-line text-muted'
            }`}
          >
            <FileIcon width={18} height={18} />
          </button>
        )}

        {/* Notifications: opens the side panel with what waits on a person (the fork, manual mode's
            choice, suggestions) and the steering instructions. The badge counts what waits. */}
        <button
          aria-label={waitingCount > 0 ? `Notifications (${waitingCount} waiting)` : 'Notifications'}
          title="Notifications: what the run needs from you"
          aria-pressed={inboxOpen}
          aria-expanded={inboxOpen}
          onClick={() => setInboxOpen((o) => !o)}
          className={`relative grid size-9.5 shrink-0 place-items-center rounded-xl border bg-elev shadow-lg shadow-black/20 transition-colors hover:bg-hover hover:text-fg ${
            inboxOpen ? 'border-fg text-fg' : 'border-line text-muted'
          }`}
        >
          <BellIcon width={18} height={18} />
          {waitingCount > 0 && (
            <span className="absolute -top-1.5 -right-1.5 grid h-4.5 min-w-4.5 animate-[node-pop_300ms_var(--ease-zoom)_both] place-items-center rounded-full bg-kind-note px-1 text-[10px] leading-none font-semibold text-black">
              {waitingCount}
            </span>
          )}
        </button>
      </div>

      {/* The notifications panel: slides out from the right, pushing the corner's buttons aside. Its
          heading sits level with them. */}
      <aside
        aria-label="Notifications"
        inert={!inboxOpen}
        style={{ width: INBOX_W, paddingTop: 23 }}
        className={`absolute inset-y-0 right-0 z-10 flex flex-col border-l border-line bg-bg shadow-xl shadow-black/20 transition-transform duration-300 ease-zoom ${
          inboxOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <h2 className="shrink-0 px-5 pb-2.5 text-xs font-semibold text-muted">Notifications</h2>
        <div className="min-h-0 flex-1 overflow-auto px-5 pb-5">
          {snapshot ? (
            <RunCards
              runId={runId}
              suggestions={snapshot.suggestions ?? []}
              nodes={treeNodes}
              canAct={canAct}
              live={live}
              apply={apply}
              pendingFork={pendingFork}
              lastFork={lastFork}
              onForkChanged={(fork) => apply((o) => o.forks.set(fork.id, fork))}
              onFocusNode={(id) => {
                setSelectedId(id)
                setConclusionOpen(false)
              }}
              onNodeAction={actOnNode}
            />
          ) : (
            <p className="px-1 text-xs text-muted">Nothing needs you right now.</p>
          )}
        </div>
        {/* The steering instructions: the bottom quarter, scrolling on its own. */}
        <section aria-label="Your instructions" className="flex h-1/4 shrink-0 flex-col border-t border-line">
          <h2 className="shrink-0 px-5 pt-3 pb-2 text-xs font-semibold text-muted">Your instructions</h2>
          <div className="min-h-0 flex-1 overflow-auto px-5 pb-4">
            <InstructionList runId={runId} instructions={snapshot?.run.instructions ?? []} canAct={canAct} apply={apply} />
          </div>
        </section>
      </aside>

      {/* The run's objectives, bottom right; they move aside with the notifications panel. */}
      <div
        inert={!toolbarShown}
        style={{ right: inboxOpen ? INBOX_W + 20 : 20 }}
        className={`absolute bottom-5 z-10 transition-[right,opacity] duration-300 ease-zoom ${
          toolbarShown ? 'opacity-100' : 'opacity-0'
        }`}
      >
        <ObjectivesChecklist objectives={snapshot?.run.objectives ?? []} met={metObjectives(treeNodes)} live={live} />
      </div>

      {selected && (
        <NodePanel
          key={selected.id}
          node={selected}
          forks={forks.filter((f) => f.node_id === selected.id && f.status === 'requested')}
          onClose={() => {
            setSelectedId(null)
            setLogsOpen(false)
            setConclusionOpen(false)
          }}
          onShowLogs={() => {
            setConclusionOpen(false)
            setPatchOpen(false)
            setLogsOpen(true)
          }}
          onShowConclusion={() => {
            setLogsOpen(false)
            setPatchOpen(false)
            setConclusionOpen(true)
          }}
          top={cornerBottom}
          right={inboxOpen ? INBOX_W + 20 : 20}
          progress={runProgress(treeNodes, snapshot?.run.objectives ?? [])}
          isRoot={!treeNodes.some((m) => m.id === selected.parent_id)}
          onAction={(action) => actOnNode(selected.id, action)}
          blockedReason={pendingFork ? 'Decide on the suggested fork first' : null}
          onConclude={() => concludeAt(selected)}
          choosing={selected.status === 'pending' && !!treeNodes.find((m) => m.id === selected.parent_id)?.awaiting_choice}
          hasConclusion={treeNodes.some((m) => m.parent_id === selected.id && m.type === 'conclusion')}
          canAct={canAct}
          // The root is on every chosen path; its popup shows the run's own state instead.
          chosen={chosen.has(selected.id) && !!selected.parent_id}
        />
      )}
      {/* Same look and spot as the vault's toolbar (top centre of the working area). */}
      <div
        role="toolbar"
        aria-label="Tree tools"
        inert={!toolbarShown}
        // Centred, unless the area is narrow (a side panel open): then it steps left, just enough to
        // clear the top-right corner (its offset + its width + a 12px gap + half the toolbar).
        style={{ left: `min(50%, 100% - ${(inboxOpen ? INBOX_W + 20 : 20) + cornerWidth + 12 + 40}px)` }}
        className={`absolute top-3 flex -translate-x-1/2 gap-1 rounded-xl border border-line bg-elev p-1 shadow-lg shadow-black/20 transition-[opacity,left] duration-300 ease-zoom ${
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

      <NodeLogsPanel
        open={logsOpen && !!selected}
        node={selected}
        entries={logs.entries}
        source={logs.source}
        onClose={() => setLogsOpen(false)}
      />

      <ConclusionPanel
        open={conclusionOpen && selected?.type === 'conclusion'}
        node={selected}
        onClose={() => setConclusionOpen(false)}
      />

      <PatchPanel open={patchOpen} runId={runId} onClose={() => setPatchOpen(false)} />
    </div>
  )
}
