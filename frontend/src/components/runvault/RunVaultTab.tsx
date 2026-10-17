import { useState } from 'react'
import { useRunVault } from '../../hooks/useRunVault'
import { personColor } from '../../lib/colors'
import DraggablePanel from '../ui/DraggablePanel'
import RunVaultGraph from './RunVaultGraph'

// "Per-run vault": what the agent itself discovered during the current run, grouped by branch.
export default function RunVaultTab({ active }: { active: boolean }) {
  const { ideas, branches } = useRunVault()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const idea = ideas.find((i) => i.id === selectedId)
  const colorOf = (branch: string) => personColor(branches, branch)

  return (
    <div className="relative h-full">
      <RunVaultGraph
        ideas={ideas}
        branches={branches}
        active={active}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />

      <header className="pointer-events-none absolute top-4 left-5">
        <h2 className="text-lg font-semibold">Run vault</h2>
        <p className="mt-0.5 text-[13px] text-muted">
          Ideas the agent found in this run · {ideas.length} ideas · {branches.length} branches
        </p>
      </header>

      <div className="absolute bottom-4 left-5 hidden max-w-md flex-wrap gap-x-3.5 gap-y-1 rounded-xl border border-line bg-elev px-3 py-2 text-xs text-muted sm:flex">
        {branches.map((b) => (
          <span key={b} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: colorOf(b) }} />
            {b}
          </span>
        ))}
      </div>

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
