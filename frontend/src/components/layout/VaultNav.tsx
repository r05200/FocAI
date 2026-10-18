import { useState } from 'react'
import { useVaultPeople } from '../../hooks/useVaultGraph'
import { personColor } from '../../lib/colors'
import { splitVaults } from '../../lib/vaultAccess'
import { useUiStore } from '../../store/uiStore'
import { useVaultStore } from '../../store/vaultStore'
import { PlusIcon, VaultIcon } from '../ui/Icons'
import AddVaultDialog from '../vault/AddVault'
import { vaultName } from '../../lib/vaultName'

// Labels show only while the sidebar is expanded (same rule as the tabs, see TabBar).
export const LABEL =
  'whitespace-nowrap opacity-0 transition-opacity duration-200 group-hover/nav:opacity-100 group-has-[:focus-visible]/nav:opacity-100'

// Takes no room at all in the collapsed rail (so the vault dots sit in one unbroken column), and
// opens up with the sidebar.
const EXPAND =
  'max-h-0 overflow-hidden opacity-0 transition-[max-height,opacity] duration-200 group-hover/nav:max-h-12 group-hover/nav:opacity-100 group-has-[:focus-visible]/nav:max-h-12 group-has-[:focus-visible]/nav:opacity-100'

const ITEM =
  'flex h-9 w-full items-center gap-3 overflow-hidden rounded-xl px-3.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-accent'

function Heading({ children }: { children: string }) {
  return (
    <div className={EXPAND}>
      <p className="px-3.5 pt-3 pb-1 text-xs font-medium whitespace-nowrap text-muted">{children}</p>
    </div>
  )
}

// The sidebar's vault section: "Vaults" with Your Vaults (can be added to, plus a button to create
// one) and Other Vaults (the team vault and teammates': view only). Picking one opens the Vault
// tab on it. In the collapsed rail only the coloured dots show, in one column: the group labels and
// the New vault entry only take room once the sidebar opens.
export default function VaultNav() {
  const people = useVaultPeople()
  const { yours, others } = splitVaults(people)
  const tab = useUiStore((s) => s.tab)
  const setTab = useUiStore((s) => s.setTab)
  const person = useVaultStore((s) => s.person)
  const setPerson = useVaultStore((s) => s.setPerson)
  const [adding, setAdding] = useState(false)

  const item = (value: string | null, label: string, color: string) => {
    const active = tab === 'vault' && person === value
    return (
      <li key={value ?? '__team'}>
        <button
          aria-label={label}
          aria-current={active ? 'page' : undefined}
          onClick={(e) => {
            setPerson(value)
            setTab('vault')
            // Same as the tabs: don't leave focus behind after a mouse click (it would pop the
            // sidebar open on the next key press).
            if (e.detail > 0) e.currentTarget.blur()
          }}
          className={`${ITEM} ${active ? 'bg-elev text-fg' : 'text-muted hover:bg-hover hover:text-fg'}`}
        >
          <span className="grid w-5 shrink-0 place-items-center">
            <span className="size-2.5 rounded-full" style={{ background: color }} />
          </span>
          <span className={`truncate ${LABEL}`}>{label}</span>
        </button>
      </li>
    )
  }

  return (
    <section aria-label="Vaults" className="mt-1 flex min-h-0 flex-col">
      <div className="flex h-10 items-center gap-3 px-3.5 text-muted">
        <VaultIcon className="shrink-0" strokeWidth={1.6} />
        <h2 className={`text-sm ${LABEL}`}>Vaults</h2>
      </div>
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
        <Heading>Your Vaults</Heading>
        <ul>
          {yours.map((p) => item(p, vaultName(p), personColor(people, p)))}
          <li className={EXPAND}>
            <button
              aria-label="New vault"
              aria-haspopup="dialog"
              onClick={(e) => {
                setAdding(true)
                if (e.detail > 0) e.currentTarget.blur()
              }}
              className={`${ITEM} text-muted hover:bg-hover hover:text-fg`}
            >
              <span className="grid w-5 shrink-0 place-items-center">
                <PlusIcon width={16} height={16} />
              </span>
              <span className={LABEL}>New vault</span>
            </button>
          </li>
        </ul>
        <Heading>Other Vaults</Heading>
        <ul>
          {item(null, vaultName(null), 'var(--color-muted)')}
          {others.map((p) => item(p, vaultName(p), personColor(people, p)))}
        </ul>
      </div>
      {adding && <AddVaultDialog people={people} onClose={() => setAdding(false)} />}
    </section>
  )
}
