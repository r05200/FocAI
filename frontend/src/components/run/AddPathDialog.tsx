import { useState, type FormEvent } from 'react'
import Modal from '../ui/Modal'

// An absolute path on the machine the backend runs on: /… or C:\… (the backend rejects relative ones).
const ABSOLUTE = /^(\/|[A-Za-z]:[\\/])/

interface Props {
  existing: string[]
  limit: number
  onAdd: (path: string) => void
  onClose: () => void
}

// Asks for a file's path. A browser never reveals where a picked file lives (only its name), so the
// path has to be typed or pasted; the backend reads the file straight from disk.
export default function AddPathDialog({ existing, limit, onAdd, onClose }: Props) {
  const [path, setPath] = useState('')
  const [error, setError] = useState<string | null>(null)

  function submit(e: FormEvent) {
    e.preventDefault()
    const value = path.trim().replace(/^["']|["']$/g, '') // drag-copied paths often come quoted
    if (!value) return setError('Enter the path of a file.')
    if (!ABSOLUTE.test(value)) return setError('Use the full path, starting with / (or C:\\ on Windows).')
    if (existing.includes(value)) return setError('That path is already added.')
    if (existing.length >= limit) return setError(`At most ${limit} paths per run.`)
    onAdd(value)
  }

  return (
    <Modal title="Add file path" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <p className="mb-4 text-xs text-muted">
          The file the run should work on, as a full path on the machine running the backend. Browsers
          can’t see where a file lives, so type or paste it (in Finder: right-click the file, hold
          Option, “Copy … as Pathname”).
        </p>
        <label className="mb-1 block text-xs font-medium text-muted" htmlFor="file-path">
          Path
        </label>
        <input
          id="file-path"
          data-autofocus
          value={path}
          placeholder="/Users/you/project/notes.md"
          autoComplete="off"
          spellCheck={false}
          aria-invalid={!!error}
          onChange={(e) => {
            setPath(e.target.value)
            setError(null)
          }}
          className={`w-full rounded-lg border bg-bg px-3 py-2 font-mono text-sm outline-none transition-colors placeholder:text-muted ${
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
          className="mt-5 h-10 w-full rounded-xl bg-accent text-sm font-semibold text-accent-fg transition-opacity hover:opacity-85"
        >
          Add path
        </button>
      </form>
    </Modal>
  )
}
