import { useState } from 'react'
import { useDirectives } from '../../hooks/useDirectives'
import { personColor } from '../../lib/colors'
import { useVaultStore } from '../../store/vaultStore'
import { CloseIcon } from '../ui/Icons'

function formatDate(seconds: number) {
  return new Date(seconds * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

// Right-hand sidebar listing directives for whoever's vault is shown. It's a flex sibling of the
// graph, so opening it narrows the map instead of covering it.
export default function DirectivesPanel({ people }: { people: string[] }) {
  const open = useVaultStore((s) => s.directivesOpen)
  const setOpen = useVaultStore((s) => s.setDirectivesOpen)
  const person = useVaultStore((s) => s.person)
  const directives = useDirectives(person)
  const removeDirective = useVaultStore((s) => s.removeDirective)
  const [failed, setFailed] = useState<string | null>(null)

  return (
    <aside
      aria-label="Directives"
      aria-hidden={!open}
      inert={!open}
      className={`shrink-0 overflow-hidden border-line bg-sidebar transition-[width] duration-200 ease-out ${
        open ? 'w-80 border-l' : 'w-0'
      }`}
    >
      <div className="flex h-full w-80 flex-col">
        <header className="flex items-center justify-between px-4 pt-4 pb-3">
          <div>
            <h2 className="font-semibold">Directives</h2>
            <p className="text-xs text-muted capitalize">
              {person ? `${person}'s` : 'Team'} · {directives.length} active
            </p>
          </div>
          <button
            aria-label="Close directives"
            onClick={() => setOpen(false)}
            className="grid size-8 place-items-center rounded-lg text-muted transition-colors hover:bg-hover hover:text-fg"
          >
            <CloseIcon />
          </button>
        </header>

        <ul className="flex-1 space-y-2 overflow-auto px-3 pb-3">
          {directives.length === 0 && (
            <li className="px-1 py-6 text-center text-sm text-muted">No directives yet.</li>
          )}
          {directives.map((d) => (
            <li key={d.id} className="group relative rounded-xl border border-line bg-elev px-3 py-2.5">
              <p className="pr-6 text-sm leading-relaxed">{d.text}</p>
              <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted">
                <span className="size-2 rounded-full" style={{ background: personColor(people, d.person) }} />
                <span className="capitalize">{d.person}</span> · {formatDate(d.created_at)}
              </p>
              {failed === d.id && <p className="mt-1 text-xs text-kind-correction">Couldn’t delete that.</p>}
              {/* DELETE /vault/directives/{id} */}
              <button
                aria-label="Delete directive"
                title="Delete"
                onClick={() => {
                  setFailed(null)
                  removeDirective(d.id).catch(() => setFailed(d.id))
                }}
                className="absolute top-2 right-2 grid size-6 place-items-center rounded-md text-muted opacity-0 transition hover:bg-hover hover:text-fg focus-visible:opacity-100 group-hover:opacity-100"
              >
                <CloseIcon />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  )
}
