import { getPatch } from '../../api/client'
import { usePolled } from '../../hooks/usePolled'
import { CloseIcon } from '../ui/Icons'

interface Props {
  open: boolean
  runId: string
  onClose: () => void
}

type Loaded = { patch: string } | { error: string }

// How a line of a unified diff is shown.
function lineStyle(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-fg font-semibold'
  if (line.startsWith('@@')) return 'text-kind-question'
  if (line.startsWith('+')) return 'bg-rel-supports/10 text-rel-supports'
  if (line.startsWith('-')) return 'bg-kind-correction/10 text-kind-correction'
  if (line.startsWith('diff ')) return 'mt-3 text-muted first:mt-0'
  return 'text-muted'
}

// Right-hand sidebar (same slot as the logs) with the changes the run left applied to the user's
// files: GET /runs/{id}/patch, a unified diff from the original files. Fetched when opened.
export default function PatchPanel({ open, runId, onClose }: Props) {
  const loaded = usePolled<Loaded>(open ? runId : null, () =>
    getPatch(runId).then(
      (patch) => ({ patch }),
      (err) => ({ error: err instanceof Error ? err.message : 'Could not load the changes.' }),
    ),
  )
  return (
    <aside
      aria-label="Changes"
      aria-hidden={!open}
      inert={!open}
      className={`shrink-0 overflow-hidden border-line bg-sidebar transition-[width] duration-300 ease-zoom ${
        open ? 'w-100 border-l' : 'w-0'
      }`}
    >
      <div className="flex h-full w-100 flex-col">
        <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-3">
          <div className="min-w-0">
            <h2 className="font-semibold">Changes</h2>
            <p className="text-xs text-muted">What the run left applied to your files</p>
          </div>
          <button
            aria-label="Close changes"
            onClick={onClose}
            className="grid size-8 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-hover hover:text-fg"
          >
            <CloseIcon />
          </button>
        </header>
        <div className="flex-1 overflow-auto px-4 pb-4">
          {!loaded && <p className="py-6 text-center text-sm text-muted">Loading…</p>}
          {loaded && 'error' in loaded && <p className="py-6 text-center text-sm text-kind-correction">{loaded.error}</p>}
          {loaded && 'patch' in loaded && !loaded.patch.trim() && (
            <p className="py-6 text-center text-sm text-muted">Nothing was kept: your files are as they were.</p>
          )}
          {loaded && 'patch' in loaded && loaded.patch.trim() && (
            <pre className="font-mono text-[11px] leading-relaxed">
              {loaded.patch.split('\n').map((line, i) => (
                <div key={i} className={`px-1 whitespace-pre-wrap wrap-anywhere ${lineStyle(line)}`}>
                  {line || ' '}
                </div>
              ))}
            </pre>
          )}
        </div>
      </div>
    </aside>
  )
}
