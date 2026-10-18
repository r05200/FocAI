import { useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { useUiStore } from '../../store/uiStore'
import { useVaultStore } from '../../store/vaultStore'
import { PERSON_PATTERN } from '../../types'
import Modal from '../ui/Modal'
import { vaultId, vaultName } from '../../lib/vaultName'

// The dialog behind the sidebar's "New vault" entry. Creates a new, empty vault of your own.
export default function AddVaultDialog({ people, onClose }: { people: string[]; onClose: () => void }) {
  const createVault = useVaultStore((s) => s.createVault)
  const setPerson = useVaultStore((s) => s.setPerson)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const value = vaultId(name)
    if (!value) return setError('Enter a name for the vault.')
    if (!PERSON_PATTERN.test(value)) {
      return setError(
        value.length > 32
          ? 'Keep the name to 32 characters or fewer.'
          : /^[_-]/.test(value)
            ? 'Start the name with a letter or number.'
            : 'Use only letters, numbers and spaces (no other symbols).',
      )
    }
    const exists = () => setError(`A vault named “${vaultName(value)}” already exists.`)
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
    // Jump straight to the new, empty vault (the dialog opens from the sidebar on any tab).
    setPerson(value)
    useUiStore.getState().setTab('vault')
    onClose()
  }

  return (
    <Modal title="New vault" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <p className="mb-4 text-xs text-muted">
          Create a vault of your own to collect papers, notes and questions. It starts empty and shows
          up under Your Vaults; add to it with the + button once it’s open.
        </p>
        <label className="mb-1 block text-xs font-medium text-muted" htmlFor="vault-name">
          Name
        </label>
        <input
          id="vault-name"
          data-autofocus
          value={name}
          placeholder="e.g. KV cache notes"
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
