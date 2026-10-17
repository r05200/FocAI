import { useState } from 'react'
import { useRunVault } from '../../hooks/useRunVault'
import { personColor } from '../../lib/colors'
import DraggablePanel from '../ui/DraggablePanel'
import { ArrowLeftIcon, IdeasIcon } from '../ui/Icons'
import RunVaultGraph from './RunVaultGraph'

interface Props {
  runId: string
  // `active`: this view is on screen (the map only renders then). `live`: the run is still going,
  // so keep refetching.
  active: boolean
  live: boolean
  onBack: () => void
}

// "Run vault": what the agent itself discovered during this run, grouped by branch. Opened from the
// button at the top right of the run's tree; "Back to run" returns to the tree.
export default function RunVaultTab({ runId, active, live, onBack }: Props) {
  const { ideas, branches, status } = useRunVault(runId, active && live)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const idea = ideas.find((i) => i.id === selectedId)
  const colorOf = (branch: string) => personColor(branches, branch)
  const empty = status !== 'loading' && ideas.length === 0

  return (
    <div className="relative h-full">
      {!empty && status !== 'loading' && (
        <RunVaultGraph
          ideas={ideas}
          branches={branches}
          active={active}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      )}

      <button
        onClick={onBack}
        className="absolute top-5 left-6 z-10 flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-fg"
      >
        <ArrowLeftIcon />
        Back to run
      </button>

      <header className="pointer-events-none absolute top-12 left-6">
        <h2 className="text-lg font-semibold">Run vault</h2>
        {!empty && status !== 'loading' && (
          <p className="mt-0.5 text-[13px] text-muted">
            Ideas the agent found in this run · {ideas.length} ideas · {branches.length} branches
          </p>
        )}
        {status === 'offline' && (
          <p className="mt-1 text-[13px] text-kind-note">Backend unreachable: showing sample ideas.</p>
        )}
      </header>

      {empty && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
          <div className="flex flex-col items-center text-muted">
            <IdeasIcon width={44} height={44} strokeWidth={1.4} />
            <p className="mt-4 text-lg font-semibold text-fg">No ideas yet</p>
            <p className="mt-1 max-w-xs text-sm">
              {status === 'unsupported'
                ? "The backend doesn't keep run vaults yet."
                : 'What the agent finds will appear here as it explores.'}
            </p>
          </div>
        </div>
      )}

      {!empty && (
        <div className="absolute bottom-4 left-5 hidden max-w-md flex-wrap gap-x-3.5 gap-y-1 rounded-xl border border-line bg-elev px-3 py-2 text-xs text-muted sm:flex">
          {branches.map((b) => (
            <span key={b} className="inline-flex items-center gap-1.5">
              <span className="size-2.5 rounded-full" style={{ background: colorOf(b) }} />
              {b}
            </span>
          ))}
        </div>
      )}

      {idea && (
        <DraggablePanel
          aria-label="Idea"
          onClose={() => setSelectedId(null)}
          label={
            <>
              <span className="size-2.5 rounded-full" style={{ background: colorOf(idea.branch) }} />
              {idea.branch}
            </>
          }
        >
          <h3 className="mt-1.5 mb-2 font-semibold">{idea.title}</h3>
          <p className="leading-relaxed text-muted">{idea.summary}</p>
        </DraggablePanel>
      )}
    </div>
  )
}
