import { BaseEdge, getSmoothStepPath, type Edge, type EdgeProps } from '@xyflow/react'
import { useId, useState } from 'react'
import { useAfter } from '../../hooks/useAfter'
import { CHOSEN_DRAW_MS, NODE_POP_MS, now, PULSE_MS, pulsePhase, UNFOLD_DRAW_MS } from '../../lib/treeAppear'

// candidate: the branch is still in play; chosen: kept (part of the chosen path); parked / stopped.
export type EdgeState = 'candidate' | 'chosen' | 'parked' | 'stopped'
type TreeEdgeData = {
  state: EdgeState
  appearDelay: number // ms after mounting that the line fades in (with the node it leads to)
  // Unfolding (opening a run): ms after mounting that the line is drawn from parent to child
  // instead of fading in; null otherwise.
  drawDelay: number | null
  pulsing: boolean // the run is going: send pulses down candidate lines
  // Manual mode: the node it leads to is one of the proposals waiting on a person's choice: a
  // yellow line is drawn to it from `choiceAt` (wall-clock ms) over `choiceMs`, instead of the pulse.
  choice?: boolean
  choiceAt?: number
  choiceMs?: number
}
export type TreeEdgeType = Edge<TreeEdgeData, 'tree'>

const BLUE = 'var(--color-kind-paper)'
const YELLOW = 'var(--color-kind-note)'
// Room around the path for the draw mask, so a straight (zero-height) line isn't clipped away.
const PAD = 16
// How far a choice's yellow ring reaches outside its node (TreeCanvas ChoiceRing: a 48px node, the
// ring 12px wider at r=48%, stroke 2.5). A line to a choice stops there, just touching the ring,
// rather than running under it and showing through as the ring pulses.
const RING_GAP = 6

// A tree edge (smoothstep, left to right). Layers:
//   - the plain line, fading in with the node it leads to (dashed when parked), or, while a tree
//     unfolds, drawn from parent to child (through a mask, so a dashed line draws too);
//   - candidate, while the run is going: a short blue dash that travels from parent to child every
//     PULSE_MS (in step with the child's ripple, see TreeCanvas);
//   - choice (manual mode): a yellow line drawn from parent to child once, instead of the pulse;
//   - chosen: a solid blue line drawn from parent to child once, which stays.
export default function TreeEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  data,
}: EdgeProps<TreeEdgeType>) {
  const [fullPath] = getSmoothStepPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })
  const [ringPath] = getSmoothStepPath({ sourceX, sourceY, sourcePosition, targetX: targetX - RING_GAP, targetY, targetPosition })
  const state = data?.state ?? 'candidate'
  const appearDelay = data?.appearDelay ?? 0
  const drawDelay = data?.drawDelay ?? null
  // The delays above count from when this edge mounted; the blue line can mount much later (the
  // branch is kept, or a conclusion lands under it), so it times itself from here.
  const [mountedAt] = useState(now)
  // The edge was already on the chosen path when it mounted (a tree opening, or arriving with a
  // kept branch): its blue line follows the line's own timing. Otherwise the branch was kept just
  // now (or a conclusion landed under it): the blue line draws at once.
  const [chosenAtMount] = useState(state === 'chosen')
  // Once a choice, the yellow line stays to hand over: picked, the blue line draws over it and it
  // fades once covered; dropped, it fades at once.
  const choice = !!data?.choice
  const [wasChoice, setWasChoice] = useState(choice)
  if (choice && !wasChoice) setWasChoice(true)
  // While its node has the ring, the line stops at the ring's edge.
  const path = choice ? ringPath : fullPath
  // Edge ids are only unique within one canvas; more than one tree can be mounted.
  const maskId = `draw-${useId()}-${id}`.replace(/[^\w-]/g, '')
  return (
    <>
      {drawDelay !== null && (
        <defs>
          <mask
            id={maskId}
            maskUnits="userSpaceOnUse"
            x={Math.min(sourceX, targetX) - PAD}
            y={Math.min(sourceY, targetY) - PAD}
            width={Math.abs(targetX - sourceX) + PAD * 2}
            height={Math.abs(targetY - sourceY) + PAD * 2}
          >
            <path
              d={path}
              fill="none"
              stroke="white"
              strokeWidth={PAD}
              pathLength={1}
              strokeDasharray="1"
              style={{ animation: `edge-draw ${UNFOLD_DRAW_MS}ms ease-in-out ${drawDelay}ms both` }}
            />
          </mask>
        </defs>
      )}
      <BaseEdge
        id={id}
        path={path}
        mask={drawDelay !== null ? `url(#${maskId})` : undefined}
        style={{
          ...style,
          ...(state === 'parked' ? { strokeDasharray: '5 4', opacity: 0.5 } : {}),
          ...(drawDelay === null ? { animation: `fade-in ${NODE_POP_MS}ms ease-out ${appearDelay}ms both` } : {}),
        }}
      />
      {state === 'candidate' && data?.pulsing && !choice && <Pulse path={path} afterMs={appearDelay + NODE_POP_MS} />}
      {/* Manual mode: the line to a choice (under the blue, which draws over it once it's picked). */}
      {wasChoice && (
        <ChoiceLine
          path={ringPath}
          startAt={data?.choiceAt ?? 0}
          ms={data?.choiceMs ?? CHOSEN_DRAW_MS}
          ending={choice ? null : state === 'chosen' ? CHOSEN_DRAW_MS : 0}
        />
      )}
      {state === 'chosen' && (
        // Drawn alongside the plain line while unfolding; otherwise once the node is there.
        <ChosenLine
          path={path}
          startAt={chosenAtMount ? mountedAt + (drawDelay ?? Math.max(appearDelay, 0)) : 0}
          ms={chosenAtMount && drawDelay !== null ? UNFOLD_DRAW_MS : CHOSEN_DRAW_MS}
        />
      )}
    </>
  )
}

// The yellow line to a choice, drawn from parent to child once from `startAt` (ms, wall clock;
// straight away if that's past). `ending`: the choice is over; it fades out after that many ms.
function ChoiceLine({ path, startAt, ms, ending }: { path: string; startAt: number; ms: number; ending: number | null }) {
  const [delay] = useState(() => Math.max(0, startAt - now()))
  return (
    <path
      d={path}
      fill="none"
      stroke={YELLOW}
      strokeWidth={2}
      pathLength={1}
      strokeDasharray="1"
      className="pointer-events-none"
      style={{
        animation: ending === null ? `edge-draw ${ms}ms var(--ease-zoom) ${delay}ms both` : `fade-out 300ms ease-out ${ending}ms both`,
      }}
    />
  )
}

// The travelling dash. Its phase is fixed when it mounts, so every pulse on the page moves together.
// It waits until the node it leads to has finished popping in (`afterMs` from now).
function Pulse({ path, afterMs }: { path: string; afterMs: number }) {
  const [phase] = useState(pulsePhase)
  const ready = useAfter(afterMs)
  if (!ready) return null
  return (
    <path
      d={path}
      fill="none"
      stroke={BLUE}
      strokeWidth={2.5}
      pathLength={1}
      strokeDasharray="0.14 2"
      className="pointer-events-none"
      // The dash travels during the first PULSE_TRAVEL_MS of each cycle (20% in the keyframes).
      style={{ animation: `edge-pulse ${PULSE_MS}ms linear ${phase}ms infinite` }}
    />
  )
}

// The chosen path's solid blue line, drawn from parent to child once, starting at `startAt` (ms, wall
// clock): straight away if that's already past, e.g. a branch kept long after its line appeared.
function ChosenLine({ path, startAt, ms }: { path: string; startAt: number; ms: number }) {
  const [delay] = useState(() => Math.max(0, startAt - now()))
  return (
    <path
      d={path}
      fill="none"
      stroke={BLUE}
      strokeWidth={2}
      pathLength={1}
      strokeDasharray="1"
      className="pointer-events-none"
      style={{ animation: `edge-draw ${ms}ms var(--ease-zoom) ${delay}ms both` }}
    />
  )
}
