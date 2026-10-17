import { useRunHistory } from '../../hooks/useRunHistory'
import { HistoryIcon } from '../ui/Icons'

function formatDate(seconds: number) {
  return new Date(seconds * 1000).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

const STATUS_STYLE = {
  running: 'text-kind-note',
  done: 'text-rel-supports',
  failed: 'text-kind-correction',
} as const

export default function HistoryTab() {
  const runs = useRunHistory()

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-8">
        <h1 className="mb-1 text-2xl font-semibold">Run history</h1>
        <p className="mb-6 text-sm text-muted">
          {runs.length} run{runs.length === 1 ? '' : 's'}
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
                {/* TODO: open the run's tree view on click. */}
                <button className="w-full rounded-2xl border border-line bg-elev px-5 py-4 text-left transition-colors hover:bg-hover">
                  <p className="leading-relaxed">{run.question}</p>
                  <p className="mt-2.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
                    <span className={`font-medium capitalize ${STATUS_STYLE[run.status]}`}>
                      {run.status}
                    </span>
                    · <span>{run.mode}</span> ·{' '}
                    <span className="capitalize">{run.primary_person}</span> ·{' '}
                    <span>{formatDate(run.created_at)}</span>
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
