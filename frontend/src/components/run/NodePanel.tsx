import { useState } from 'react'
import { formatScore } from '../../lib/format'
import { nodeState } from '../../lib/nodeStatus'
import type { RunProgress } from '../../lib/runProgress'
import type { ForkRequest, HumanAction, TreeNode } from '../../types'
import DraggablePanel from '../ui/DraggablePanel'

const VERDICT_STYLE = {
  supported: 'text-rel-supports',
  refuted: 'text-kind-correction',
  inconclusive: 'text-muted',
} as const

const DIRECTION_LABEL = {
  better: { text: '↑ better than last round', style: 'text-rel-supports' },
  worse: { text: '↓ worse than last round', style: 'text-kind-correction' },
  same: { text: '= same as last round', style: 'text-muted' },
} as const

const PENDING_LABEL: Record<HumanAction, string> = {
  keep: 'Will be kept once its current step finishes.',
  park: 'Will be parked once its current step finishes.',
  restore: 'Will be restored once its current step finishes.',
}

// Up to this many measured numbers are listed (the logs have the rest).
const METRICS_SHOWN = 6

// The small popup shown when a tree node is clicked (same draggable card as the vault's).
export default function NodePanel({
  node,
  forks,
  onClose,
  onShowLogs,
  top,
  right,
  isRoot,
  onAction,
  onConclude,
  hasConclusion,
  choosing,
  blockedReason,
  canAct,
  chosen,
  progress,
  onShowConclusion,
}: {
  node: TreeNode
  forks: ForkRequest[]
  onClose: () => void
  onShowLogs: () => void
  top: number // default distance from the top of the tree area, below what's in the corner
  right?: number // default distance from the right (clear of the notifications panel when it's open)
  isRoot: boolean
  // Keep / park / restore (POST .../nodes/{id}/<action>); rejects with the backend's reason.
  onAction: (action: HumanAction) => Promise<void>
  // End exploration here: the node's subtree gives way to a conclusion (POST .../conclude).
  onConclude: () => Promise<void>
  hasConclusion: boolean // the node already has its conclusion
  // Manual mode: this is one of the proposals the run waits on a choice between (its parent is
  // awaiting_choice): Keep reads "Run this next" and Park "Drop it".
  choosing: boolean
  // The run is still going: a finished or stopped run's nodes can't be acted on.
  canAct: boolean
  // Why node actions are off while the run is still going (e.g. a fork waits on a decision).
  blockedReason: string | null
  chosen: boolean // on the chosen path
  // Where the run stands (the root's popup shows it).
  progress: RunProgress | null
  onShowConclusion: () => void
}) {
  const isConclusion = node.type === 'conclusion'
  const [busy, setBusy] = useState<HumanAction | 'conclude' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const act = (action: HumanAction | 'conclude') => {
    setBusy(action)
    setError(null)
    ;(action === 'conclude' ? onConclude() : onAction(action)).then(
      () => setBusy(null),
      (err) => {
        setBusy(null)
        setError(err instanceof Error ? err.message : `Could not ${action} that node.`)
      },
    )
  }

  // Which actions fit (the backend refuses the rest with 409): none on the root (the baseline) or
  // the conclusion (the run's answer), or on a node that failed.
  const actionable = !isRoot && !isConclusion && node.status !== 'failed'
  const keptByHand = node.decision?.stage === 'human' && node.decision.verdict === 'keep'
  const canKeep = actionable && node.status !== 'parked' && !keptByHand && !chosen
  const canPark = actionable && node.status !== 'parked'
  const canRestore = actionable && node.status === 'parked'
  const canConclude = canPark && !hasConclusion
  const h = node.hypothesis
  const metrics = Object.entries(node.experiment?.metrics ?? {}).slice(0, METRICS_SHOWN)

  return (
    <DraggablePanel
      aria-label="Node"
      top={top}
      right={right}
      onClose={onClose}
      label={
        <>
          <span className={`size-2.5 rounded-full ${nodeState(node, chosen).dot}`} />
          {/* The header capitalizes every word; state labels are sentences. */}
          <span className="normal-case">{isRoot ? `Root · ${nodeState(node, chosen).label}` : nodeState(node, chosen).label}</span>
          {node.family && !isRoot && <span className="normal-case">· {node.family}</span>}
        </>
      }
    >
      <h3 className="mt-1.5 mb-2 font-semibold">{node.description}</h3>

      {/* The full proposal: description is only its short title. */}
      {h && !isRoot && !isConclusion && h.statement && h.statement !== node.description && (
        <p className="mb-2.5 leading-relaxed text-muted">{h.statement}</p>
      )}

      {(node.pre_score || node.post_score !== null || node.pre_band) && (
        <p className="mb-2.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          {node.pre_score && <span>Pre-score {formatScore(node.pre_score.overall)}</span>}
          {!node.pre_score && node.pre_band && <span className="capitalize">Pre-score {node.pre_band}</span>}
          {node.post_score !== null && <span>Post-score {formatScore(node.post_score)}</span>}
          {node.tokens.total > 0 && <span>{node.tokens.total.toLocaleString()} tokens</span>}
        </p>
      )}

      {/* What the judge made of the experiment. */}
      {node.synthesis && !isConclusion && (
        <p className="mb-2.5 leading-relaxed text-muted">
          <span className={`font-semibold capitalize ${VERDICT_STYLE[node.synthesis.verdict]}`}>{node.synthesis.verdict}: </span>
          {node.synthesis.finding}
          {node.synthesis.direction && node.synthesis.direction !== 'unclear' && (
            <span className={`mt-0.5 block text-xs ${DIRECTION_LABEL[node.synthesis.direction].style}`}>
              {DIRECTION_LABEL[node.synthesis.direction].text}
            </span>
          )}
        </p>
      )}

      {node.awaiting_choice && (
        <p className="mb-2.5 text-xs leading-relaxed text-kind-note">
          Its proposals are ready: choose which one runs next (Run this next on it), or drop the others.
        </p>
      )}

      {metrics.length > 0 && (
        <dl className="mb-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 rounded-lg bg-hover px-3 py-2 font-mono text-[11px]">
          {metrics.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="truncate text-muted">{k}</dt>
              <dd className="text-right">{Number.isInteger(v) ? v : v.toFixed(3)}</dd>
            </div>
          ))}
        </dl>
      )}
      {node.experiment?.error && (
        <p className="mb-2.5 text-xs text-kind-correction">Experiment error: {node.experiment.error}</p>
      )}

      {node.decision && (
        <p className="mb-2.5 leading-relaxed text-muted">
          <span className="font-semibold text-fg">{node.decision.verdict === 'keep' ? 'Kept' : 'Parked'}: </span>
          {node.decision.reason}
        </p>
      )}

      {node.directive_reason && (
        <p className="mb-2.5 text-xs leading-relaxed text-muted">
          <span className="font-semibold text-fg">For your instructions: </span>
          {node.directive_reason}
        </p>
      )}

      {forks.map((f) => (
        <p key={f.id} className="mb-2.5 leading-relaxed text-muted">
          <span className="font-semibold text-fg">Fork suggested here: </span>
          {f.reason}
        </p>
      ))}

      {isRoot && progress && <Progress progress={progress} />}

      {/* A node's output. Not on the root (the run's answer lives on the conclusion node) or the
          conclusion itself (it opens in its own sidebar). */}
      {node.result && !isRoot && !isConclusion && (
        <p className="mb-3 line-clamp-4 leading-relaxed text-muted">{node.result}</p>
      )}

      {node.pending_action && <p className="mb-2.5 text-xs text-kind-note">{PENDING_LABEL[node.pending_action]}</p>}

      <button
        onClick={onShowLogs}
        className="h-7 w-full rounded-lg border border-line text-sm transition-colors hover:bg-hover"
      >
        Show logs
      </button>

      {isConclusion && (
        <button
          onClick={onShowConclusion}
          className="mt-2 h-7 w-full rounded-lg bg-accent text-sm font-medium text-accent-fg transition-opacity hover:opacity-85"
        >
          Show conclusion
        </button>
      )}

      {(canKeep || canPark || canRestore) && (
        <div className="mt-2 flex gap-2">
          {canKeep && (
            <button
              onClick={() => act('keep')}
              disabled={busy !== null || !canAct}
              title={canAct ? 'Make sure this branch stays (it moves up the queue)' : (blockedReason ?? 'This run has ended')}
              className="h-7 flex-1 rounded-lg border border-kind-paper text-sm text-kind-paper transition-colors hover:bg-kind-paper/10 disabled:opacity-50"
            >
              {busy === 'keep' ? (choosing ? 'Choosing…' : 'Keeping…') : choosing ? 'Run this next' : 'Keep node'}
            </button>
          )}
          {canPark && (
            <button
              onClick={() => act('park')}
              disabled={busy !== null || !canAct}
              title={canAct ? undefined : (blockedReason ?? 'This run has ended')}
              className="h-7 flex-1 rounded-lg border border-kind-correction text-sm text-kind-correction transition-colors hover:bg-kind-correction/10 disabled:opacity-50"
            >
              {busy === 'park' ? 'Parking…' : choosing ? 'Drop it' : 'Park node'}
            </button>
          )}
          {canRestore && (
            <button
              onClick={() => act('restore')}
              disabled={busy !== null || !canAct}
              title={canAct ? 'Bring this branch back; the run continues from it' : (blockedReason ?? 'This run has ended')}
              className="h-7 flex-1 rounded-lg border border-kind-paper text-sm text-kind-paper transition-colors hover:bg-kind-paper/10 disabled:opacity-50"
            >
              {busy === 'restore' ? 'Restoring…' : 'Restore node'}
            </button>
          )}
        </div>
      )}
      {canConclude && (
        <button
          onClick={() => act('conclude')}
          disabled={busy !== null || !canAct}
          title={canAct ? 'Stop exploring here: what is under this node is dropped and a conclusion is drawn from it' : (blockedReason ?? 'This run has ended')}
          className="mt-2 h-7 w-full rounded-lg border border-line text-sm transition-colors hover:bg-hover disabled:opacity-50"
        >
          {busy === 'conclude' ? 'Concluding…' : 'Conclude'}
        </button>
      )}
      {blockedReason && (canKeep || canPark || canRestore) && <p className="mt-1 text-xs text-muted">{blockedReason}.</p>}
      {error && <p className="mt-1 text-xs text-kind-correction">{error}</p>}
    </DraggablePanel>
  )
}

// The root's view of the run: objectives met (the bar) and how the branches are going.
function Progress({ progress: p }: { progress: RunProgress }) {
  const parts = [
    p.done && `${p.done} done`,
    p.running && `${p.running} running`,
    p.pending && `${p.pending} pending`,
    p.parked && `${p.parked} parked`,
    p.stopped && `${p.stopped} stopped`,
  ].filter(Boolean)
  const share = p.objectivesTotal > 0 ? p.objectivesMet / p.objectivesTotal : 0
  return (
    <div className="mb-3 rounded-lg bg-hover px-3 py-2.5">
      <p className="mb-1.5 text-xs font-semibold">Progress</p>
      {p.objectivesTotal > 0 && (
        <>
          <div className="h-1.5 overflow-hidden rounded-full bg-line">
            <div className="h-full rounded-full bg-kind-paper transition-[width] duration-500" style={{ width: `${share * 100}%` }} />
          </div>
          <p className="mt-1.5 text-xs text-muted">
            {p.objectivesMet} of {p.objectivesTotal} objectives met
          </p>
        </>
      )}
      <p className={`text-xs text-muted ${p.objectivesTotal > 0 ? 'mt-0.5' : ''}`}>
        {p.branches === 0 ? 'No branches yet' : `${p.branches} branch${p.branches === 1 ? '' : 'es'}: ${parts.join(' · ')}`}
      </p>
    </div>
  )
}
