import { useRunHistory } from '../../hooks/useRunHistory'
import { formatDateTime } from '../../lib/format'
import { runEnd } from '../../lib/nodeStatus'
import { useRunStore } from '../../store/runStore'
import { useUiStore } from '../../store/uiStore'
import { HistoryIcon } from '../ui/Icons'
import { vaultName } from '../../lib/vaultName'

// The backend's RunMode values are "pruned" / "unpruned"; the UI calls pruning "parking".
const MODE_LABEL = { pruned: 'parked', unpruned: 'unparked' } as const

export default function HistoryTab({ active }: { active: boolean }) {
  // Refetched each time the tab is opened (GET /runs), so new and finished runs show up.
  const { runs, loading, offline } = useRunHistory(active)
  const openRun = useRunStore((s) => s.openRun)
  const setTab = useUiStore((s) => s.setTab)

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-8">
        <h1 className="mb-1 text-2xl font-semibold">Run history</h1>
        <p className="mb-6 text-sm text-muted">
          {loading ? 'Loading…' : `${runs.length} run${runs.length === 1 ? '' : 's'}`}
          {offline && <span className="text-kind-note"> · backend unreachable, showing a sample</span>}
        </p>

        {runs.length === 0 ? (
          <div className="grid place-items-center py-24 text-center text-muted">
            <div className="flex flex-col items-center">
              <HistoryIcon width={32} height={32} />
              <p className="mt-3">No runs yet.</p>
            </div>
          </div>
        ) : (
          <ul className="space-y-3">
            {runs.map((run) => (
              <li key={run.id}>
                {/* Opens the run on the Research tab (its tree is still just a root for now). */}
                <button
                  onClick={() => {
                    openRun(run)
                    setTab('run')
                  }}
                  className="w-full rounded-2xl border border-line bg-elev px-5 py-4 text-left transition-colors hover:bg-hover">
                  <p title={run.question} className="line-clamp-2 leading-relaxed wrap-anywhere">{run.question}</p>
                  <p className="mt-2.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
                    <span className={`font-medium ${runEnd(run).style}`}>{runEnd(run).label}</span>
                    · <span>{MODE_LABEL[run.mode]}</span> ·{' '}
                    <span>{vaultName(run.primary_person)}</span> ·{' '}
                    <span>{formatDateTime(run.created_at)}</span>
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
