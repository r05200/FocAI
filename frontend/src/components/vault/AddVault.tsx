import { useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { useVaultStore } from '../../store/vaultStore'
import { PERSON_PATTERN } from '../../types'
import { AddVaultIcon } from '../ui/Icons'
import Modal from '../ui/Modal'

// Turn what was typed into a name: trim, lowercase, spaces become hyphens.
const normalize = (raw: string) => raw.trim().toLowerCase().replace(/\s+/g, '-')

// Button (violet, vault-with-plus icon: deliberately unlike the white + that adds knowledge) and
// the dialog it opens. Creates a new, empty vault for a team member.
export default function AddVault({ people }: { people: string[] }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        aria-label="Add vault"
        aria-haspopup="dialog"
        title="Add vault"
        onClick={() => setOpen(true)}
        className="grid size-9.5 place-items-center rounded-xl bg-kind-question text-white transition-opacity hover:opacity-85"
      >
        <AddVaultIcon />
      </button>
      {open && <AddVaultDialog people={people} onClose={() => setOpen(false)} />}
    </>
  )
}

function AddVaultDialog({ people, onClose }: { people: string[]; onClose: () => void }) {
  const createVault = useVaultStore((s) => s.createVault)
  const setPerson = useVaultStore((s) => s.setPerson)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const value = normalize(name)
    if (!value) return setError('Enter a name for the vault.')
    if (!PERSON_PATTERN.test(value)) {
      return setError(
        value.length > 32
          ? 'Keep the name to 32 characters or fewer.'
          : /^[_-]/.test(value)
            ? 'Start the name with a letter or number.'
            : 'Use only letters, numbers, - and _ (no other symbols).',
      )
    }
    const exists = () => setError(`A vault named “${value}” already exists.`)
    if (people.includes(value)) return exists()

    setSaving(true)
    try {
      // POST /vault/vaults (the store falls back to a local-only vault if the backend is down).
      await createVault(value)
    } catch (err) {
      setSaving(false)
      if (err instanceof ApiError && err.status === 409) return exists()
      return setError(err instanceof Error ? err.message : 'Could not create the vault.')
    }
    setPerson(value) // jump straight to the new, empty vault
    onClose()
  }

  return (
    <Modal title="Add vault" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <p className="mb-4 text-xs text-muted">
          A vault holds one team member’s papers, notes and questions. It starts empty; add knowledge to
          it with the + button.
        </p>
        <label className="mb-1 block text-xs font-medium text-muted" htmlFor="vault-name">
          Name
        </label>
        <input
          id="vault-name"
          data-autofocus
          value={name}
          placeholder="e.g. carol"
          autoComplete="off"
          spellCheck={false}
          aria-invalid={!!error}
          onChange={(e) => {
            setName(e.target.value)
            setError(null)
          }}
          className={`w-full rounded-lg border bg-bg px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted ${
            error ? 'border-kind-correction' : 'border-line focus:border-fg'
          }`}
        />
        {error && (
          <p role="alert" className="mt-1 text-xs text-kind-correction">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={saving}
          className="mt-5 h-10 w-full rounded-xl bg-kind-question text-sm font-semibold text-white transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {saving ? 'Creating…' : 'Create vault'}
        </button>
      </form>
    </Modal>
  )
}
