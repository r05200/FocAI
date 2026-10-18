import { useState } from 'react'
import type { Objective } from '../../types'
import { CheckIcon, ChevronDownIcon } from '../ui/Icons'

interface Props {
  objectives: Objective[]
  met: ReadonlySet<string> // ids some finished node has advanced
  live: boolean // the run is going (objectives may still be on their way)
}

// The run's objectives as a checklist, in the tree's top-right corner. A tick means some finished
// node advanced that objective. Folds down to its header.
export default function ObjectivesChecklist({ objectives, met, live }: Props) {
  const [open, setOpen] = useState(true)
  const done = objectives.filter((o) => met.has(o.id)).length
  return (
    <section
      aria-label="Objectives"
      className="w-[min(280px,calc(100vw-200px))] rounded-xl border border-line bg-elev text-sm shadow-lg shadow-black/20"
    >
      <button
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex h-9.5 w-full items-center gap-2 rounded-xl px-3 text-left"
      >
        <span className="font-medium">Objectives</span>
        {objectives.length > 0 && (
          <span className="text-xs text-muted">
            {done}/{objectives.length}
          </span>
        )}
        <ChevronDownIcon className={`ml-auto text-muted transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <ul className="max-h-64 space-y-1.5 overflow-auto px-3 pb-3">
          {objectives.length === 0 && (
            <li className="text-xs text-muted">{live ? 'Being written…' : 'None were written.'}</li>
          )}
          {objectives.map((o) => {
            const checked = met.has(o.id)
            return (
              <li key={o.id} className="flex items-start gap-2">
                <span
                  aria-label={checked ? 'Met' : 'Not met yet'}
                  className={`mt-0.5 grid size-4 shrink-0 place-items-center rounded border ${
                    checked ? 'border-kind-paper bg-kind-paper text-white' : 'border-line'
                  }`}
                >
                  {checked && <CheckIcon width={11} height={11} strokeWidth={3} />}
                </span>
                <span className={`text-xs leading-relaxed wrap-anywhere ${checked ? 'text-muted line-through' : ''}`}>
                  {o.text}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
