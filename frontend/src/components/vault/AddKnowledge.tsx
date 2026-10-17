import { useRef, useState, type FormEvent } from 'react'
import { KIND_COLOR } from '../../lib/colors'
import { useVaultStore, type AddableKind } from '../../store/vaultStore'
import type { VaultItemView } from '../../types'
import { CloseIcon, FolderIcon, PlusIcon } from '../ui/Icons'
import Modal from '../ui/Modal'

// 'correction' and 'learned' are written by the system, so they aren't offered here.
const TYPES: { kind: AddableKind; label: string; hint: string }[] = [
  { kind: 'paper', label: 'Paper', hint: 'Add a link, a file, or both.' },
  { kind: 'note', label: 'Note', hint: 'Your own notes or findings. Shows up in the vault.' },
  { kind: 'question', label: 'Question', hint: 'Something you want answered. Shows up in the vault.' },
  { kind: 'directive', label: 'Directive', hint: 'A standing instruction for the agent. Listed in the directives sidebar.' },
]

const TEXT_PLACEHOLDER: Record<Exclude<AddableKind, 'paper'>, string> = {
  note: 'Write your note…',
  question: 'What do you want to find out?',
  directive: 'e.g. Prefer optimizer changes over architecture changes.',
}

interface Errors {
  text?: string
  link?: string
  file?: string
  paper?: string // shared message shown under both paper inputs
}

function isUrl(value: string) {
  try {
    const u = new URL(value)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

const field =
  'w-full rounded-lg border bg-bg px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted'
const ok = 'border-line focus:border-fg'
const bad = 'border-kind-correction focus:border-kind-correction'

function ErrorText({ children }: { children?: string }) {
  return children ? (
    <p role="alert" className="mt-1 text-xs text-kind-correction">
      {children}
    </p>
  ) : null
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s
}

// "+" button plus the dialog it opens. `author` is whose vault the new entry goes into; without
// one (no vaults exist yet) there is nowhere to add to, so the button is disabled.
export default function AddKnowledge({ author }: { author?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        aria-label="Add to vault"
        aria-haspopup="dialog"
        title={author ? 'Add to vault' : 'No vaults yet'}
        disabled={!author}
        onClick={() => setOpen(true)}
        className="grid size-9.5 place-items-center rounded-xl bg-accent text-accent-fg transition-opacity hover:opacity-85 disabled:opacity-30"
      >
        <PlusIcon />
      </button>
      {open && author && <AddDialog author={author} onClose={() => setOpen(false)} />}
    </>
  )
}

function AddDialog({ author, onClose }: { author: string; onClose: () => void }) {
  const kind = useVaultStore((s) => s.addKind)
  const setKind = useVaultStore((s) => s.setAddKind)
  const addItem = useVaultStore((s) => s.addItem)
  const addDirective = useVaultStore((s) => s.addDirective)
  const setDirectivesOpen = useVaultStore((s) => s.setDirectivesOpen)

  // Each type only has its own fields: paper takes a link and/or file, the rest take text.
  // Switching type clears everything, so nothing typed for one type leaks into another.
  const [text, setText] = useState('')
  const [link, setLink] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<Errors>({})
  const fileInput = useRef<HTMLInputElement>(null)

  const hint = TYPES.find((t) => t.kind === kind)!.hint

  function changeKind(next: AddableKind) {
    setKind(next)
    setText('')
    setLink('')
    setFile(null)
    if (fileInput.current) fileInput.current.value = ''
    setErrors({})
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    const body = text.trim()
    const url = link.trim()
    const next: Errors = {}

    if (kind === 'paper') {
      if (!url && !file) next.paper = 'Add a link or attach a file.'
      else if (url && !isUrl(url)) next.link = 'Enter a valid link starting with http:// or https://.'
    } else if (!body) {
      next.text = {
        note: 'Write something before adding.',
        question: 'Write your question before adding.',
        directive: 'Write the directive before adding.',
      }[kind]
    }
    setErrors(next)
    if (Object.keys(next).length) return

    // TODO: send to the backend instead of keeping it in memory:
    //   items      -> POST /api/vault/items      { person, kind, text, title? }
    //   directives -> POST /api/vault/directives { person, text }
    // The ingest route only takes `text`, so a paper link/file needs the backend to fetch or
    // upload and extract the text first.
    const now = Date.now() / 1000
    const id = `local_${Date.now()}`
    if (kind === 'directive') {
      addDirective({ id: `dir_${id}`, person: author, text: body, created_at: now })
      setDirectivesOpen(true)
    } else {
      const paper = kind === 'paper'
      const title = paper
        ? (file?.name ?? new URL(url).hostname.replace(/^www\./, ''))
        : truncate(body.split('\n')[0], 60)
      const item: VaultItemView = {
        id,
        person: author,
        kind,
        title,
        summary: paper ? (url || (file?.name ?? '')) : body,
        tags: [],
        source_text: paper ? url : body,
        investigate: false, // the backend's ingest LLM decides this
        retrieval_count: 0,
        created_at: now,
      }
      addItem(item)
    }
    onClose()
  }

  return (
    <Modal title="Add to vault" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <label className="mb-1 block text-xs font-medium text-muted" htmlFor="add-type">
          Type
        </label>
        <div className="relative">
          <span
            className="pointer-events-none absolute top-1/2 left-3 size-2.5 -translate-y-1/2 rounded-full"
            style={{ background: KIND_COLOR[kind] }}
          />
          <select
            id="add-type"
            value={kind}
            onChange={(e) => changeKind(e.target.value as AddableKind)}
            className={`${field} ${ok} appearance-none pl-8`}
          >
            {TYPES.map((t) => (
              <option key={t.kind} value={t.kind}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <p className="mt-1.5 mb-4 text-xs text-muted">{hint}</p>

        {kind === 'paper' ? (
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted" htmlFor="add-link">
                Link
              </label>
              <input
                id="add-link"
                type="url"
                value={link}
                placeholder="https://arxiv.org/abs/…"
                aria-invalid={!!(errors.link || errors.paper)}
                onChange={(e) => {
                  setLink(e.target.value)
                  setErrors({})
                }}
                className={`${field} ${errors.link || errors.paper ? bad : ok}`}
              />
              <ErrorText>{errors.link}</ErrorText>
            </div>

            <div>
              <span className="mb-1 block text-xs font-medium text-muted">File</span>
              <input
                ref={fileInput}
                type="file"
                hidden
                accept=".pdf,.txt,.md,.doc,.docx"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null)
                  setErrors({})
                }}
              />
              <div
                className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 transition-colors ${
                  errors.paper ? bad : ok
                }`}
              >
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-line px-2.5 text-sm transition-colors hover:bg-hover"
                >
                  <FolderIcon width={14} height={14} />
                  Choose file
                </button>
                {file ? (
                  <>
                    <span className="min-w-0 flex-1 truncate text-sm">{file.name}</span>
                    <button
                      type="button"
                      aria-label="Remove file"
                      onClick={() => {
                        setFile(null)
                        if (fileInput.current) fileInput.current.value = ''
                      }}
                      className="grid size-6 place-items-center rounded-full text-muted hover:text-fg"
                    >
                      <CloseIcon />
                    </button>
                  </>
                ) : (
                  <span className="text-sm text-muted">No file chosen</span>
                )}
              </div>
              <ErrorText>{errors.paper}</ErrorText>
            </div>
          </div>
        ) : (
          <div>
            <label className="sr-only" htmlFor="add-text">
              {kind}
            </label>
            <textarea
              id="add-text"
              rows={5}
              value={text}
              placeholder={TEXT_PLACEHOLDER[kind]}
              aria-invalid={!!errors.text}
              onChange={(e) => {
                setText(e.target.value)
                setErrors({})
              }}
              className={`${field} ${errors.text ? bad : ok} resize-none leading-relaxed`}
            />
            <ErrorText>{errors.text}</ErrorText>
          </div>
        )}

        <button
          type="submit"
          className="mt-5 h-10 w-full rounded-xl bg-accent text-sm font-semibold text-accent-fg transition-opacity hover:opacity-85"
        >
          Add
        </button>
      </form>
    </Modal>
  )
}
