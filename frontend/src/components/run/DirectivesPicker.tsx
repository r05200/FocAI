import { useMemo, useState } from 'react'
import { useDirectivesIn } from '../../hooks/useDirectives'
import { useVaultPeople } from '../../hooks/useVaultGraph'
import { personColor } from '../../lib/colors'
import { formatDate } from '../../lib/format'
import { CheckIcon } from '../ui/Icons'
import Modal from '../ui/Modal'
import { vaultName } from '../../lib/vaultName'

interface Props {
  vaults: string[]
  selected: string[] // directive ids
  onApply: (vaults: string[], selected: string[]) => void
  onClose: () => void
}

// Pick which standing directives go with this run. Choose one or more vaults (their directives
// are pooled: any selected vault), then tick the directives to include.
export default function DirectivesPicker({ vaults: initialVaults, selected: initialSelected, onApply, onClose }: Props) {
  const people = useVaultPeople()
  const [vaults, setVaults] = useState<string[]>(initialVaults)
  const [selected, setSelected] = useState<Set<string>>(() => new Set(initialSelected))
  const directives = useDirectivesIn(vaults)
  const visibleIds = useMemo(() => directives.map((d) => d.id), [directives])
  // Only directives still on screen count: dropping a vault drops its ticked directives too.
  const chosen = visibleIds.filter((id) => selected.has(id))
  const allChosen = visibleIds.length > 0 && chosen.length === visibleIds.length

  function toggleVault(p: string) {
    setVaults((v) => (v.includes(p) ? v.filter((x) => x !== p) : [...v, p]))
  }

  function toggle(id: string) {
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    setSelected((s) => {
      const next = new Set(s)
      for (const id of visibleIds) {
        if (allChosen) next.delete(id)
        else next.add(id)
      }
      return next
    })
  }

  return (
    <Modal title="Add directives" size="lg" onClose={onClose}>
      <p className="mb-2 text-xs font-medium text-muted">Vaults</p>
      <div className="mb-1 flex flex-wrap gap-1.5" role="group" aria-label="Vaults">
        {people.map((p) => {
          const on = vaults.includes(p)
          return (
            <button
              key={p}
              type="button"
              aria-pressed={on}
              onClick={() => toggleVault(p)}
              className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors ${
                on ? 'border-fg bg-hover text-fg' : 'border-line text-muted hover:bg-hover hover:text-fg'
              }`}
            >
              <span className="size-2 rounded-full" style={{ background: personColor(people, p) }} />
              {vaultName(p)}
            </button>
          )
        })}
      </div>
      <p className="mb-4 text-xs text-muted">Shows directives from any of the selected vaults.</p>

      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-medium text-muted">
          Directives{vaults.length > 0 && ` · ${chosen.length} of ${directives.length} selected`}
        </p>
        {directives.length > 0 && (
          <button type="button" onClick={toggleAll} className="text-xs text-muted hover:text-fg">
            {allChosen ? 'Select none' : 'Select all'}
          </button>
        )}
      </div>

      <div className="h-72 overflow-auto rounded-xl border border-line bg-bg p-2">
        {vaults.length === 0 ? (
          <div className="grid h-full place-items-center text-sm text-muted">Pick a vault</div>
        ) : directives.length === 0 ? (
          <div className="grid h-full place-items-center text-sm text-muted">
            No directives in {vaults.length === 1 ? 'this vault' : 'these vaults'}
          </div>
        ) : (
          <ul className="space-y-2">
            {directives.map((d) => {
              const on = selected.has(d.id)
              return (
                <li key={d.id}>
                  <label
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors ${
                      on ? 'border-fg/60 bg-elev' : 'border-line bg-elev hover:bg-hover'
                    }`}
                  >
                    <input type="checkbox" checked={on} onChange={() => toggle(d.id)} className="peer sr-only" />
                    <span
                      aria-hidden="true"
                      className={`mt-0.5 grid size-4.5 shrink-0 place-items-center rounded-md border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-fg ${
                        on ? 'border-accent bg-accent text-accent-fg' : 'border-muted'
                      }`}
                    >
                      {on && <CheckIcon width={12} height={12} />}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm leading-relaxed">{d.text}</span>
                      <span className="mt-1 flex items-center gap-1.5 text-xs text-muted">
                        <span className="size-2 rounded-full" style={{ background: personColor(people, d.person) }} />
                        <span>{vaultName(d.person)}</span> · {formatDate(d.created_at)}
                      </span>
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="mt-5 flex gap-2">
        <button
          type="button"
          onClick={onClose}
          className="h-10 flex-1 rounded-xl border border-line text-sm transition-colors hover:bg-hover"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => onApply(vaults, chosen)}
          className="h-10 flex-1 rounded-xl bg-accent text-sm font-semibold text-accent-fg transition-opacity hover:opacity-85"
        >
          {chosen.length === 0 ? 'Use no directives' : `Use ${chosen.length} directive${chosen.length === 1 ? '' : 's'}`}
        </button>
      </div>
    </Modal>
  )
}
