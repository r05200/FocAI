import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import ForceGraph3D, { type ForceGraphMethods, type LinkObject, type NodeObject } from 'react-force-graph-3d'
import { MOUSE, type Object3D, type PerspectiveCamera } from 'three'
import type { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { EASE_OUT, flyCamera, type Flight, type Vec3 } from '../../lib/cameraFly'
import { CARD_H, CARD_W } from '../../lib/vaultSprites'
import { SIDEBAR_RAIL } from '../../store/uiStore'
import { useVaultStore, type VaultTool } from '../../store/vaultStore'
import { CursorIcon, FitIcon, HandIcon, MinusIcon, PlusIcon, TargetIcon } from '../ui/Icons'

const FOCUS_DIST = 900 // camera distance when focused on the central node (shows its neighbourhood)
const FLY_FROM = 2600 // how far out the fly-in starts
const FLATTEN = 0.06 // pull toward z=0: head-on it reads like a 2D map, rotating reveals depth

type Control = 'in' | 'out' | 'center' | 'fit'
const CONTROLS = [
  { action: 'in', label: 'Zoom in', Icon: PlusIcon },
  { action: 'out', label: 'Zoom out', Icon: MinusIcon },
  { action: 'center', label: 'Recenter', Icon: TargetIcon },
  { action: 'fit', label: 'Fit everything', Icon: FitIcon },
] as const satisfies readonly { action: Control; label: string; Icon: unknown }[]

const TOOLS = [
  { tool: 'select', label: 'Select & rotate', key: 'V', Icon: CursorIcon },
  { tool: 'pan', label: 'Pan (hold Space)', key: 'H', Icon: HandIcon },
] as const satisfies readonly { tool: VaultTool; label: string; key: string; Icon: unknown }[]

// Custom d3 force: damps z so the layout stays mostly flat but keeps some real depth.
function flattenZ(strength: number) {
  let nodes: { z?: number; vz?: number }[] = []
  const force = (alpha: number) => {
    for (const n of nodes) n.vz = (n.vz ?? 0) - (n.z ?? 0) * strength * alpha
  }
  force.initialize = (ns: typeof nodes) => {
    nodes = ns
  }
  return force
}

function isTyping(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))
  )
}

// Full title on hover, following the pointer. Kept separate so mouse moves don't re-render the graph.
function HoverTooltip({
  info,
  box,
}: {
  info: { title: string; subtitle: string } | null
  box: RefObject<HTMLDivElement | null>
}) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const active = info !== null
  useEffect(() => {
    const el = box.current
    if (!el || !active) return
    const onMove = (e: PointerEvent) => {
      // Over a panel or button the graph doesn't report un-hover, so hide it ourselves.
      if (!(e.target instanceof HTMLCanvasElement) || !el.contains(e.target)) return setPos(null)
      const r = el.getBoundingClientRect()
      setPos({ x: e.clientX - r.left, y: e.clientY - r.top })
    }
    window.addEventListener('pointermove', onMove)
    return () => window.removeEventListener('pointermove', onMove)
  }, [active, box])
  if (!info || !pos) return null
  return (
    <div
      className="pointer-events-none absolute z-10 max-w-xs rounded-lg border border-line bg-elev px-2.5 py-1.5 text-[13px] shadow-lg shadow-black/30"
      style={{ left: pos.x + 14, top: pos.y + 14 }}
    >
      <div className="font-medium">{info.title}</div>
      <div className="mt-0.5 text-xs text-muted">{info.subtitle}</div>
    </div>
  )
}

export interface MindMapNode {
  id: string
  label: string
}

export interface MindMapProps<N extends MindMapNode, L extends object> {
  data: { nodes: N[]; links: L[] }
  active: boolean
  // Camera lands on this node when opening/recentering; null = the middle of all cards.
  focusId: string | null
  selectedId: string | null
  onSelect: (id: string | null) => void
  // Build the 3D object for a card. Must be a new function when its look changes (palette).
  nodeObject: (node: N, selected: boolean) => Object3D
  tooltip: (node: N) => { title: string; subtitle: string }
  // Omit for a link-free map.
  linkColor?: (link: L) => string
  // How the camera frames the map when the tab opens: on the focus point, or zoomed out to fit
  // every card (better for maps that are spread out).
  openWith?: 'focus' | 'fit'
  // Changing this re-runs the fly-in (e.g. pass the selected person).
  resetKey?: string
  // Extra d3 forces / tuning, e.g. grouping. Applied before the first layout, and again (with a
  // re-layout) if it changes. Keep it memoized.
  configureForces?: (g: ForceGraphMethods<NodeObject<N>, LinkObject<N, L>>) => void
}

export default function MindMap3D<N extends MindMapNode, L extends object>({
  data,
  active,
  focusId,
  selectedId,
  onSelect,
  nodeObject: buildObject,
  tooltip,
  linkColor,
  openWith = 'focus',
  resetKey,
  configureForces,
}: MindMapProps<N, L>) {
  type Node = NodeObject<N>
  const tool = useVaultStore((s) => s.tool)
  const setTool = useVaultStore((s) => s.setTool)
  const [spaceHeld, setSpaceHeld] = useState(false)
  const [hovered, setHovered] = useState<Node | null>(null)
  const panning = tool === 'pan' || spaceHeld

  const fg = useRef<ForceGraphMethods<Node, LinkObject<N, L>> | undefined>(undefined)
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  // Rebuilding sprites is the expensive part; only redo it when their inputs change.
  const nodeObject = useMemo(
    () => (n: Node) => buildObject(n, n.id === selectedId),
    [buildObject, selectedId],
  )

  // The canvas has a fixed size: as wide as the page can ever give the map (window minus the
  // collapsed sidebar rail). It's anchored to the container's top-left, so when the sidebar or
  // directives panel slide, the map travels along with its container and the container just
  // clips it. The canvas itself is never resized mid-animation (that made it jitter); it is only
  // resized when the window is.
  useEffect(() => {
    const el = box.current
    if (!el) return
    const measure = () => {
      const next = { width: Math.max(window.innerWidth - SIDEBAR_RAIL, 1), height: el.clientHeight }
      setSize((s) => (s.width === next.width && s.height === next.height ? s : next))
    }
    measure()
    // Height changes only with the window; a container ResizeObserver would fire per frame.
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  // Forces must be in place before the first layout runs, so the graph is mounted empty, forces
  // are set up, and only then does it get the real data (its warm-up then lays out with them).
  // They are deliberately NOT re-applied on resize: reheating on every frame of the sidebar
  // animation kept pushing unlinked clusters further apart.
  const [forcesSet, setForcesSet] = useState(false)
  const ready = size.width > 0
  useEffect(() => {
    const g = fg.current
    if (!g) return
    g.d3Force('link')?.distance(150).strength(0.4)
    g.d3Force('charge')?.strength(-220)
    g.d3Force('flatten', flattenZ(FLATTEN))
    configureForces?.(g)
    if (forcesSet) g.d3ReheatSimulation()
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time gate after the graph mounts
    else setForcesSet(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- forcesSet only gates the first run
  }, [ready, configureForces])
  const graphData = useMemo(() => (forcesSet ? data : { nodes: [], links: [] }), [forcesSet, data])

  // Hidden views keep their WebGL canvas mounted; stop rendering it while off screen.
  useEffect(() => {
    const g = fg.current
    if (!g) return
    if (active) g.resumeAnimation()
    else g.pauseAnimation()
  }, [active, ready])

  const flight = useRef<Flight | null>(null)

  // Where "centre" is: the focus card if there is one, otherwise the middle of all cards together.
  function focusPoint(): Vec3 | null {
    const placed = (data.nodes as Node[]).filter((n) => n.x !== undefined)
    if (placed.length === 0) return null
    if (focusId) {
      const n = placed.find((d) => d.id === focusId) ?? placed[0]
      return { x: n.x ?? 0, y: n.y ?? 0, z: n.z ?? 0 }
    }
    const sum = placed.reduce((a, n) => ({ x: a.x + (n.x ?? 0), y: a.y + (n.y ?? 0), z: a.z + (n.z ?? 0) }), { x: 0, y: 0, z: 0 })
    return { x: sum.x / placed.length, y: sum.y / placed.length, z: sum.z / placed.length }
  }

  // Current camera and where it's looking, as plain numbers.
  function cameraState() {
    const g = fg.current!
    const p = g.camera().position
    const t = (g.controls() as OrbitControls).target
    return { pos: { x: p.x, y: p.y, z: p.z }, look: { x: t.x, y: t.y, z: t.z } }
  }

  function fly(to: { pos: Vec3; look: Vec3 }, ms: number, from = cameraState(), ease?: (x: number) => number) {
    const g = fg.current
    if (!g) return
    flight.current?.cancel()
    flight.current = flyCamera(from, to, ms, (pos, look) => g.cameraPosition(pos, look, 0), ease)
  }

  // Unit vector from the look target out to the camera: keeps the current viewing angle.
  function viewDir() {
    const { pos, look } = cameraState()
    const d = { x: pos.x - look.x, y: pos.y - look.y, z: pos.z - look.z }
    const len = Math.hypot(d.x, d.y, d.z) || 1
    return { x: d.x / len, y: d.y / len, z: d.z / len }
  }

  function focusCentral(ms: number, intro = false) {
    const look = focusPoint()
    if (!look) return
    if (intro) {
      // Start far out, straight on, then glide in.
      const to = openWith === 'fit' ? fitPose({ x: 0, y: 0, z: 1 }) : null
      const end = to ?? { pos: { ...look, z: look.z + FOCUS_DIST }, look }
      const from = { pos: { ...end.look, z: end.look.z + FLY_FROM }, look: end.look }
      fg.current?.cameraPosition(from.pos, from.look, 0)
      return fly(end, ms, from, EASE_OUT)
    }
    const d = viewDir()
    fly({ pos: { x: look.x + d.x * FOCUS_DIST, y: look.y + d.y * FOCUS_DIST, z: look.z + d.z * FOCUS_DIST }, look }, ms)
  }

  // Camera pose that frames every card when viewed along `dir`.
  function fitPose(dir: Vec3): { pos: Vec3; look: Vec3 } | null {
    const g = fg.current
    const nodes = data.nodes as Node[]
    if (!g || nodes.length === 0) return null
    const xs = nodes.map((n) => n.x ?? 0)
    const ys = nodes.map((n) => n.y ?? 0)
    const zs = nodes.map((n) => n.z ?? 0)
    const mid = (v: number[]) => (Math.min(...v) + Math.max(...v)) / 2
    const look = { x: mid(xs), y: mid(ys), z: mid(zs) }
    const halfW = (Math.max(...xs) - Math.min(...xs)) / 2 + CARD_W / 2
    const halfH = (Math.max(...ys) - Math.min(...ys)) / 2 + CARD_H / 2
    const cam = g.camera() as PerspectiveCamera
    const tanV = Math.tan((cam.fov * Math.PI) / 360)
    const dist = Math.max(halfH / tanV, halfW / (tanV * cam.aspect)) * 1.2 + 120
    return { pos: { x: look.x + dir.x * dist, y: look.y + dir.y * dist, z: look.z + dir.z * dist }, look }
  }

  // Frame every card, keeping the current viewing angle.
  function fitAll(ms: number) {
    const to = fitPose(viewDir())
    if (to) fly(to, ms)
  }

  // Grabbing the map (drag or wheel) takes over from any running animation.
  useEffect(() => {
    const el = box.current
    if (!el) return
    const stop = () => flight.current?.cancel()
    el.addEventListener('pointerdown', stop)
    el.addEventListener('wheel', stop, { passive: true })
    return () => {
      el.removeEventListener('pointerdown', stop)
      el.removeEventListener('wheel', stop)
      flight.current?.cancel()
    }
  }, [])

  // Fly in on tab entry and when `resetKey` changes (e.g. switching whose vault is shown), once
  // the real layout exists. Plain data changes (an added card) don't move the camera.
  useEffect(() => {
    if (active && ready && forcesSet) focusCentral(1400, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on entry / view switch
  }, [active, ready, forcesSet, resetKey])

  // Select tool: left-drag rotates. Pan tool or Space: left-drag moves. Right-drag does the other.
  useEffect(() => {
    const controls = fg.current?.controls() as OrbitControls | undefined
    if (!controls) return
    controls.mouseButtons = {
      LEFT: panning ? MOUSE.PAN : MOUSE.ROTATE,
      MIDDLE: MOUSE.DOLLY,
      RIGHT: panning ? MOUSE.ROTATE : MOUSE.PAN,
    }
  }, [panning, ready])

  // Space = temporary pan; V / H switch tools. Only while the vault is on screen.
  useEffect(() => {
    if (!active) return
    function onKeyDown(e: KeyboardEvent) {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.code === 'Space') {
        e.preventDefault()
        setSpaceHeld(true)
      } else if (e.key === 'v' || e.key === 'V') setTool('select')
      else if (e.key === 'h' || e.key === 'H') setTool('pan')
    }
    function onKeyUp(e: KeyboardEvent) {
      if (e.code === 'Space') setSpaceHeld(false)
    }
    const release = () => setSpaceHeld(false)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', release)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', release)
      release()
    }
  }, [active, setTool])

  function onControl(action: Control) {
    if (!fg.current) return
    if (action === 'fit') return fitAll(900)
    if (action === 'center') return focusCentral(900)
    const { pos, look } = cameraState()
    // Zoom toward the point being looked at; chained clicks continue from the current spot.
    const k = action === 'in' ? 0.7 : 1 / 0.7
    fly(
      { pos: { x: look.x + (pos.x - look.x) * k, y: look.y + (pos.y - look.y) * k, z: look.z + (pos.z - look.z) * k }, look },
      500,
    )
  }

  return (
    <div
      ref={box}
      className={`absolute inset-0 overflow-hidden ${panning ? 'cursor-grab active:cursor-grabbing' : ''}`}
    >
      <div
        className="absolute top-0 left-0"
        style={{ width: size.width, height: size.height }}
      >
        {ready && (
          <ForceGraph3D<N, L>
            ref={fg}
            width={size.width}
            height={size.height}
            graphData={graphData}
            controlType="orbit"
            backgroundColor="rgba(0,0,0,0)"
            showNavInfo={false}
            enableNodeDrag={false}
            showPointerCursor={!panning}
            warmupTicks={300}
            cooldownTicks={100}
            nodeThreeObject={nodeObject}
            nodeLabel={() => ''}
            linkVisibility={!!linkColor}
            linkColor={(l) => linkColor?.(l as L) ?? 'transparent'}
            linkWidth={0.8}
            linkOpacity={0.9}
            linkCurvature={0.25}
            onNodeHover={(n) => setHovered(panning || !active ? null : n)}
            onNodeClick={(n) => !panning && onSelect(n.id as string)}
            onBackgroundClick={() => !panning && onSelect(null)}
          />
        )}
      </div>

      <HoverTooltip info={hovered && active ? tooltip(hovered as unknown as N) : null} box={box} />

      <div
        role="toolbar"
        aria-label="Vault tools"
        className="absolute top-4 left-1/2 flex -translate-x-1/2 gap-1 rounded-xl border border-line bg-elev p-1 shadow-lg shadow-black/20"
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

      <div className="absolute right-5 bottom-4 flex gap-1.5">
        {CONTROLS.map(({ action, label, Icon }) => (
          <button
            key={action}
            aria-label={label}
            title={label}
            onClick={() => onControl(action)}
            className="grid size-9 place-items-center rounded-full border border-line bg-elev transition-colors hover:bg-hover"
          >
            <Icon />
          </button>
        ))}
      </div>
    </div>
  )
}
