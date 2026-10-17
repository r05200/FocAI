import { useState } from 'react'
import { formatScore } from '../../lib/format'
import { nodeStatusLabel, STATUS_DOT } from '../../lib/nodeStatus'
import type { ForkRequest, TreeNode } from '../../types'
import DraggablePanel from '../ui/DraggablePanel'

// The small popup shown when a tree node is clicked (same draggable card as the vault's).
export default function NodePanel({
  node,
  forks,
  onClose,
  onShowLogs,
  logsOpen,
  isRoot,
  onPark,
}: {
  node: TreeNode
  forks: ForkRequest[]
  onClose: () => void
  onShowLogs: () => void
  logsOpen: boolean
  isRoot: boolean
  onPark: () => Promise<void>
}) {
  const [parking, setParking] = useState(false)
  const [parkError, setParkError] = useState<string | null>(null)
  const park = () => {
    setParking(true)
    setParkError(null)
    onPark().then(
      () => setParking(false),
      (err) => {
        setParking(false)
        setParkError(err instanceof Error ? err.message : 'Could not park that node.')
      },
    )
  }

  return (
    <DraggablePanel
      aria-label="Node"
      // Step left of the logs sidebar while it's open (it's 400px wide).
      rightInset={logsOpen ? 400 : 0}
      onClose={onClose}
      label={
        <>
          <span className={`size-2.5 rounded-full ${STATUS_DOT[node.status]}`} />
          {isRoot ? 'Root' : node.type} · {nodeStatusLabel(node.status)}
        </>
      }
    >
      <h3 className="mt-1.5 mb-2 font-semibold">{node.description}</h3>

      {(node.pre_score || node.post_score !== null) && (
        <p className="mb-2.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          {node.pre_score && <span>Pre-score {formatScore(node.pre_score.overall)}</span>}
          {node.post_score !== null && <span>Post-score {formatScore(node.post_score)}</span>}
          {node.tokens.total > 0 && <span>{node.tokens.total.toLocaleString()} tokens</span>}
        </p>
      )}

      {node.decision && (
        <p className="mb-2.5 leading-relaxed text-muted">
          <span className="font-semibold text-fg">{node.decision.verdict === 'keep' ? 'Kept' : 'Parked'}: </span>
          {node.decision.reason}
        </p>
      )}

      {forks.map((f) => (
        <p key={f.id} className="mb-2.5 leading-relaxed text-muted">
          <span className="font-semibold text-fg">Fork requested: </span>
          {f.reason}
        </p>
      ))}

      {node.result && <p className="mb-3 line-clamp-4 leading-relaxed text-muted">{node.result}</p>}

      <button
        onClick={onShowLogs}
        className="h-9 w-full rounded-lg border border-line text-sm transition-colors hover:bg-hover"
      >
        Show logs
      </button>

      {!isRoot && node.status !== 'parked' && (
        <>
          <button
            onClick={park}
            disabled={parking}
            className="mt-2 h-9 w-full rounded-lg text-sm text-kind-correction transition-colors hover:bg-kind-correction/10 disabled:opacity-50"
          >
            {parking ? 'Parking…' : 'Park node'}
          </button>
          {parkError && <p className="mt-1 text-xs text-kind-correction">{parkError}</p>}
        </>
      )}
    </DraggablePanel>
  )
}
