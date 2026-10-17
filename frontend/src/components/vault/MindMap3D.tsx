import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import ForceGraph3D, { type ForceGraphMethods, type LinkObject, type NodeObject } from 'react-force-graph-3d'
import { MOUSE, Plane, Raycaster, Vector2, Vector3, type Object3D, type PerspectiveCamera } from 'three'
import type { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { isTyping, useSpacePan } from '../../hooks/useSpacePan'
import { EASE_OUT, flyCamera, type Flight, type Vec3 } from '../../lib/cameraFly'
import { CARD_H, CARD_W } from '../../lib/vaultSprites'
import { SIDEBAR_RAIL } from '../../store/uiStore'
import { useVaultStore, type VaultTool } from '../../store/vaultStore'
import { CursorIcon, FitIcon, HandIcon, LayoutIcon, MinusIcon, MoveIcon, PlusIcon, ResetViewIcon, TargetIcon } from '../ui/Icons'

const FOCUS_DIST = 900 // camera distance when focused on the central node (shows its neighbourhood)
const FLY_FROM = 2600 // how far out the fly-in starts
const FLATTEN = 0.06 // pull toward z=0: head-on it reads like a 2D map, rotating reveals depth

type Control = 'in' | 'out' | 'center' | 'reset' | 'fit'
const CONTROLS = [
  { action: 'in', label: 'Zoom in', Icon: PlusIcon },
  { action: 'out', label: 'Zoom out', Icon: MinusIcon },
  { action: 'center', label: 'Recenter', Icon: TargetIcon },
  { action: 'reset', label: 'Reset orientation', Icon: ResetViewIcon },
  { action: 'fit', label: 'Fit everything', Icon: FitIcon },
] as const satisfies readonly { action: Control; label: string; Icon: unknown }[]

const TOOLS = [
  { tool: 'select', label: 'Select & rotate', key: 'V', Icon: CursorIcon },
  { tool: 'pan', label: 'Pan (hold Space)', key: 'H', Icon: HandIcon },
  { tool: 'move', label: 'Move cards', key: 'M', Icon: MoveIcon },
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
  // Show the Move tool: drag a card to reposition it. Called once, when the drop happens, with the
  // card's new coordinates (it stays pinned there). Omit both to make the map read-only.
  onNodeMoved?: (id: string, position: { x: number; y: number; z: number }) => void
  // Adds a "Re-arrange" button that asks for a fresh automatic layout (the graph then updates).
  onRelayout?: () => void | Promise<void>
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
  onNodeMoved,
  onRelayout,
  configureForces,
}: MindMapProps<N, L>) {
  type Node = NodeObject<N>
  const tool = useVaultStore((s) => s.tool)
  const setTool = useVaultStore((s) => s.setTool)
  const [hovered, setHovered] = useState<Node | null>(null)
  const movable = !!onNodeMoved
  const spaceHeld = useSpacePan(active)
  const panning = tool === 'pan' || spaceHeld
  // A map without Move shouldn't be stuck on it because another map (or an earlier visit) chose it.
  const moving = movable && tool === 'move' && !panning

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

  // The camera as it is when the tab first opens: straight on (looking along -z, so the map reads
  // as flat), framed on the focus card or on everything, depending on `openWith`.
  function homePose(): { pos: Vec3; look: Vec3 } | null {
    const look = focusPoint()
    if (!look) return null
    const fit = openWith === 'fit' ? fitPose({ x: 0, y: 0, z: 1 }) : null
    return fit ?? { pos: { ...look, z: look.z + FOCUS_DIST }, look }
  }

  function focusCentral(ms: number, intro = false) {
    const look = focusPoint()
    if (!look) return
    if (intro) {
      // Start far out, straight on, then glide in.
      const end = homePose()!
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

  // On tab entry the camera is already at its home pose: the tab switch does the zooming, and a
  // fly-in from far out would show the map tiny and off-centre while the view fades in. When
  // `resetKey` changes on screen (e.g. switching whose vault is shown) it flies in. Both wait for
  // the real layout; plain data changes (an added card) don't move the camera.
  const shownFor = useRef<{ key: unknown } | null>(null)
  useEffect(() => {
    if (!active || !ready || !forcesSet) return
    const switched = shownFor.current !== null && shownFor.current.key !== resetKey
    shownFor.current = { key: resetKey }
    if (switched) return focusCentral(1400, true)
    flight.current?.cancel()
    const home = homePose()
    if (home) fg.current?.cameraPosition(home.pos, home.look, 0)
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

  // 3d-force-graph declares `enableNodeDrag` with triggerUpdate: false, so its card-drag handling
  // is only built or torn down on the next graph update. Force one when the Move tool toggles.
  useEffect(() => {
    fg.current?.refresh()
  }, [moving])

  // After a card is dropped, 3d-force-graph fires a synthetic touch "pointerup" at the document to
  // reset the camera controls. With OrbitControls in this three.js version that crashes ("reading
  // 'x'"), and it isn't needed: the real pointerup right after already resets them. Swallow just
  // that one event, flagged by onNodeDragEnd.
  const dropping = useRef(false)

  // ---- Move tool: a card moves on its own, flat in the map's plane.
  // The library drags in a camera-facing plane and keeps the simulation warm while dragging, so
  // links tug neighbours along and the centre force re-centres the whole map (it looks like the
  // camera drifting). Instead: every other card is frozen for the drag and until the layout comes
  // to rest, and the dragged card is re-placed on each move where the pointer ray meets the plane
  // parallel to the map (z = the card's depth when grabbed).
  const hoveredRef = useRef<Node | null>(null)
  const pointer = useRef({ x: 0, y: 0 })
  const drag = useRef<{ z: number; offset: { x: number; y: number } } | null>(null)
  const frozen = useRef<Node[]>([]) // cards pinned only for the duration of a drag

  // Where the pointer ray hits the plane z = `z`, in graph coordinates (null if edge-on).
  function pointOnPlane(clientX: number, clientY: number, z: number) {
    const g = fg.current
    if (!g) return null
    const rect = g.renderer().domElement.getBoundingClientRect()
    const ndc = new Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1)
    const ray = new Raycaster()
    ray.setFromCamera(ndc, g.camera())
    return ray.ray.intersectPlane(new Plane(new Vector3(0, 0, 1), -z), new Vector3())
  }

  useEffect(() => {
    const el = box.current
    if (!el) return
    const onMove = (e: PointerEvent) => {
      pointer.current = { x: e.clientX, y: e.clientY }
    }
    // Capture phase, so it runs before the graph's own handlers start a drag.
    const onDown = (e: PointerEvent) => {
      pointer.current = { x: e.clientX, y: e.clientY }
      const n = hoveredRef.current
      if (!moving || !n || e.button !== 0) return void (drag.current = null)
      const z = n.z ?? 0
      const hit = pointOnPlane(e.clientX, e.clientY, z)
      drag.current = { z, offset: hit ? { x: (n.x ?? 0) - hit.x, y: (n.y ?? 0) - hit.y } : { x: 0, y: 0 } }
    }
    el.addEventListener('pointermove', onMove, { capture: true })
    el.addEventListener('pointerdown', onDown, { capture: true })
    return () => {
      el.removeEventListener('pointermove', onMove, { capture: true })
      el.removeEventListener('pointerdown', onDown, { capture: true })
    }
  }, [moving])

  function onCardDrag(n: Node) {
    setHovered(null)
    const d = drag.current
    if (!d) return
    if (frozen.current.length === 0) {
      // First move of this drag: freeze every card that isn't already pinned.
      for (const other of data.nodes as Node[]) {
        if (other === n || other.fx !== undefined) continue
        Object.assign(other, { fx: other.x, fy: other.y, fz: other.z })
        frozen.current.push(other)
      }
    }
    const hit = pointOnPlane(pointer.current.x, pointer.current.y, d.z)
    if (!hit) return // looking at the map edge-on: hold the card where it is
    const p = { x: hit.x + d.offset.x, y: hit.y + d.offset.y, z: d.z }
    Object.assign(n, { x: p.x, y: p.y, z: p.z, fx: p.x, fy: p.y, fz: p.z })
    ;(n as Node & { __threeObj?: Object3D }).__threeObj?.position.set(p.x, p.y, p.z)
  }

  // Once the layout is at rest again, let the cards frozen for a drag go back to the layout.
  // (With the simulation stopped, un-pinning them doesn't move anything.)
  function onEngineStop() {
    if (drag.current) return
    for (const n of frozen.current) {
      delete n.fx
      delete n.fy
      delete n.fz
    }
    frozen.current = []
  }
  useEffect(() => {
    const swallow = (e: PointerEvent) => {
      if (dropping.current && !e.isTrusted && e.pointerType === 'touch') {
        dropping.current = false
        e.stopImmediatePropagation()
      }
    }
    document.addEventListener('pointerup', swallow, { capture: true })
    return () => document.removeEventListener('pointerup', swallow, { capture: true })
  }, [])

  // V / H / M switch tools, only while the vault is on screen. (Space = temporary pan: useSpacePan.)
  useEffect(() => {
    if (!active) return
    function onKeyDown(e: KeyboardEvent) {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'v' || e.key === 'V') setTool('select')
      else if (e.key === 'h' || e.key === 'H') setTool('pan')
      else if ((e.key === 'm' || e.key === 'M') && movable) setTool('move')
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [active, setTool, movable])

  function onControl(action: Control) {
    if (!fg.current) return
    if (action === 'fit') return fitAll(900)
    if (action === 'center') return focusCentral(900)
    if (action === 'reset') {
      // Back to the original view: same angle and framing as when the tab opened.
      const home = homePose()
      return home ? fly(home, 1100) : undefined
    }
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
            enableNodeDrag={moving}
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
            onNodeDrag={onCardDrag}
            onNodeDragEnd={(n) => {
              // The library lets go of a dragged card when dropped; pin it where it landed so the
              // layout leaves it alone, then report the spot.
              const { x = 0, y = 0, z = 0 } = n
              Object.assign(n, { fx: x, fy: y, fz: z })
              drag.current = null
              onNodeMoved?.(n.id as string, { x, y, z })
              dropping.current = true // see the swallow effect above
              setTimeout(() => (dropping.current = false), 0)
            }}
            onEngineStop={onEngineStop}
            onNodeHover={(n) => {
              hoveredRef.current = n
              setHovered(panning || !active ? null : n)
            }}
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
        {TOOLS.filter((t) => t.tool !== 'move' || movable).map(({ tool: t, label, key, Icon }) => {
          const on = t === 'pan' ? panning : t === 'move' ? moving : !panning && !moving
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
        {onRelayout && (
          <button
            aria-label="Re-arrange cards"
            title="Re-arrange cards (cards you moved stay put)"
            onClick={() => void onRelayout()}
            className="grid size-9 place-items-center rounded-full border border-line bg-elev transition-colors hover:bg-hover"
          >
            <LayoutIcon />
          </button>
        )}
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
