import { BaseEdge, getSmoothStepPath, type Edge, type EdgeProps } from '@xyflow/react'
import { useId } from 'react'
import { EDGE_DRAW_MS } from '../../lib/treeAppear'

export type GrowEdgeData = { drawDelay: number }
export type GrowEdgeType = Edge<GrowEdgeData, 'grow'>

// Room around the path for the mask, so a straight (zero-height) edge isn't clipped away.
const PAD = 16

// A smoothstep edge that draws itself from the source to the target, `drawDelay` ms after it mounts.
// The visible path keeps whatever style it's given (e.g. dashed for parked) and is revealed through
// a mask whose stroke grows along the same path, so the effect doesn't fight the edge's own dashes.
export default function GrowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  data,
}: EdgeProps<GrowEdgeType>) {
  const [path] = getSmoothStepPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })
  // Edge ids are only unique within one canvas; more than one tree can be mounted.
  const maskId = `grow-${useId()}-${id}`.replace(/[^\w-]/g, '')
  const x = Math.min(sourceX, targetX) - PAD
  const y = Math.min(sourceY, targetY) - PAD
  return (
    <>
      <defs>
        <mask
          id={maskId}
          maskUnits="userSpaceOnUse"
          x={x}
          y={y}
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
            style={{ animation: `edge-draw ${EDGE_DRAW_MS}ms var(--ease-zoom) ${data?.drawDelay ?? 0}ms both` }}
          />
        </mask>
      </defs>
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} mask={`url(#${maskId})`} />
    </>
  )
}
