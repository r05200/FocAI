import { useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { CloseIcon } from './Icons'

interface Props {
  // Small line at the top left of the header (e.g. a coloured dot and "alice · paper").
  label: ReactNode
  onClose: () => void
  children: ReactNode
  'aria-label': string
  // Distance from the top of the area in the default spot, in px.
  top?: number
}

// Floating card the user can drag by its header (the little grip pill signals that). It's as wide as
// its text needs, between 260 and 380px, and long words wrap instead of spilling out. Positions
// are relative to the nearest positioned ancestor and clamped inside it. Once moved, the spot
// sticks for as long as this component stays mounted.
export default function DraggablePanel({ label, onClose, children, 'aria-label': ariaLabel, top = 64 }: Props) {
  const panel = useRef<HTMLElement>(null)
  const drag = useRef<{ dx: number; dy: number; maxX: number; maxY: number } | null>(null)
  // null = default spot (top right). w / h: the card's size, so it can be kept inside the area if
  // the area later narrows (e.g. a sidebar opens).
  const [pos, setPos] = useState<{ x: number; y: number; w: number; h: number } | null>(null)

  function onDragStart(e: PointerEvent<HTMLDivElement>) {
    const el = panel.current
    const parent = el?.offsetParent as HTMLElement | null
    if (!el || !parent || (e.target as HTMLElement).closest('button')) return
    drag.current = {
      dx: e.clientX - el.offsetLeft,
      dy: e.clientY - el.offsetTop,
      maxX: parent.clientWidth - el.offsetWidth,
      maxY: parent.clientHeight - el.offsetHeight,
    }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function onDragMove(e: PointerEvent<HTMLDivElement>) {
    const d = drag.current
    if (!d) return
    const el = panel.current
    setPos({
      x: Math.min(Math.max(e.clientX - d.dx, 0), Math.max(d.maxX, 0)),
      y: Math.min(Math.max(e.clientY - d.dy, 0), Math.max(d.maxY, 0)),
      w: el?.offsetWidth ?? 0,
      h: el?.offsetHeight ?? 0,
    })
  }

  return (
    <aside
      ref={panel}
      aria-label={ariaLabel}
      style={
        pos
          ? { left: `max(0px, min(${pos.x}px, 100% - ${pos.w}px))`, top: `max(0px, min(${pos.y}px, 100% - ${pos.h}px))` }
          : { right: 20, top }
      }
      className={`absolute z-20 flex max-h-[calc(100%-90px)] w-max max-w-[min(380px,calc(100%-32px))] min-w-65 flex-col overflow-hidden rounded-xl border border-line bg-elev text-sm shadow-xl shadow-black/30 ${
        pos ? '' : 'transition-[top] duration-300 ease-zoom'
      }`}
    >
      <div
        onPointerDown={onDragStart}
        onPointerMove={onDragMove}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
        title="Drag to move"
        className="shrink-0 cursor-grab touch-none px-4 pt-1.5 pb-1 text-xs text-muted select-none active:cursor-grabbing"
      >
        {/* Grip tab: signals the panel can be dragged. */}
        <div aria-hidden="true" className="mx-auto mb-1.5 h-1 w-10 rounded-full bg-muted/40" />
        <div className="flex items-center justify-between">
          <span className="inline-flex items-center gap-1.5 capitalize">{label}</span>
          <button aria-label="Close" onClick={onClose} className="p-0.5 hover:text-fg">
            <CloseIcon />
          </button>
        </div>
      </div>
      <div className="overflow-auto px-4 pb-3.5 [overflow-wrap:anywhere]">{children}</div>
    </aside>
  )
}
