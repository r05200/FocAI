import { useRef, useState, type FormEvent } from 'react'
import { useDirectivesIn } from '../../hooks/useDirectives'
import { useVaultGraph } from '../../hooks/useVaultGraph'
import { ACCEPT, checkPicked } from '../../lib/attachments'
import { KIND_COLOR } from '../../lib/colors'
import { useVaultStore, type AddableKind } from '../../store/vaultStore'
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

// Longest text each kind accepts. Directives are short, standing instructions that get pasted
// into every prompt, so they're kept tight.
const TEXT_LIMIT: Record<Exclude<AddableKind, 'paper'>, number> = {
  note: 5000,
  question: 1000,
  directive: 500,
}
const LINK_LIMIT = 2000
// Text read from a paper's attached file is kept up to this long.
const PAPER_TEXT_LIMIT = 20000
const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()

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
  const ingest = useVaultStore((s) => s.ingest)
  const addDirective = useVaultStore((s) => s.addDirective)
  const [saving, setSaving] = useState(false)
  const setDirectivesOpen = useVaultStore((s) => s.setDirectivesOpen)

  // Each type only has its own fields: paper takes a link and/or file, the rest take text.
  // Switching type clears everything, so nothing typed for one type leaks into another.
  const [text, setText] = useState('')
  const [link, setLink] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<Errors>({})
  const fileInput = useRef<HTMLInputElement>(null)
  // What this vault already holds, to refuse duplicates.
  const { graph } = useVaultGraph(author)
  const directives = useDirectivesIn([author])

  const hint = TYPES.find((t) => t.kind === kind)!.hint

  function changeKind(next: AddableKind) {
    setKind(next)
    setText('')
    setLink('')
    setFile(null)
    if (fileInput.current) fileInput.current.value = ''
    setErrors({})
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    const body = text.trim()
    const url = link.trim()
    const next: Errors = {}

    if (kind === 'paper') {
      if (!url && !file) next.paper = 'Add a link or attach a file.'
      else if (url && !isUrl(url)) next.link = 'Enter a valid link starting with http:// or https://.'
      else if (url.length > LINK_LIMIT) next.link = `That link is too long (over ${LINK_LIMIT.toLocaleString()} characters).`
      // A read link is stored as "<link>\n\n<page text>": compare its first line.
      else if (url && graph.nodes.some((n) => n.kind === 'paper' && same(n.source_text.split('\n')[0] ?? '', url))) {
        next.link = 'That link is already in this vault.'
      } else if (!url && file && graph.nodes.some((n) => n.kind === 'paper' && same(n.title, file.name))) {
        next.file = `“${file.name}” is already in this vault.`
      }
    } else {
      const limit = TEXT_LIMIT[kind]
      if (!body) {
        next.text = {
          note: 'Write something before adding.',
          question: 'Write your question before adding.',
          directive: 'Write the directive before adding.',
        }[kind]
      } else if (body.length > limit) {
        next.text = `Keep it under ${limit.toLocaleString()} characters (it’s ${body.length.toLocaleString()}).`
      } else if (
        kind === 'directive'
          ? directives.some((d) => same(d.text, body))
          : graph.nodes.some((n) => n.kind === kind && same(n.source_text, body))
      ) {
        next.text = `That ${kind} is already in this vault.`
      }
    }
    setErrors(next)
    if (Object.keys(next).length) return

    setSaving(true)
    try {
      if (kind === 'directive') {
        // POST /vault/directives. Directives live in their own list (not the map): show it.
        await addDirective(author, body)
        setDirectivesOpen(true)
      } else if (kind === 'paper') {
        // POST /vault/items takes text only, so a paper is sent as its link plus whatever text can
        // be read from the file here. The backend fetches a bare link and reads its abstract (an
        // unreadable page is filed with "No summary found."). FIXME: PDFs/Word files can't be read
        // in the browser, so an attached one only sends its name.
        const raw = file && /\.(txt|md|markdown|csv|json|tex|html)$/i.test(file.name) ? await file.text() : ''
        // Capped like a note would be: the whole text is stored and sent back with every graph.
        const fileText = raw.trim().slice(0, PAPER_TEXT_LIMIT)
        // A bare link is fetched and its abstract read by the backend, which it only does when the
        // text is nothing but the link: an unreadable file's name would stop that, so it's left out.
        const text = url ? [url, fileText].filter(Boolean).join('\n\n') : fileText || `(attached file: ${file!.name})`
        await ingest({
          person: author,
          kind,
          text,
          // A bare link gets its title from the page (the backend fetches it); a file keeps its name.
          title: file?.name,
        })
      } else {
        // POST /vault/items: the vault LLM writes the title, summary and tags and links it up.
        await ingest({ person: author, kind, text: body })
      }
    } catch (err) {
      setSaving(false)
      const message = err instanceof Error ? err.message : 'Could not add that.'
      return setErrors(kind === 'paper' ? { paper: message } : { text: message })
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
                accept={ACCEPT.file}
                onChange={(e) => {
                  const picked = e.target.files?.[0]
                  if (fileInput.current) fileInput.current.value = '' // re-picking the same file still fires
                  if (!picked) return
                  // Same checks as the (parked) attachments feature: type, size, not empty.
                  const { accepted, errors: problems } = checkPicked('file', [picked], [])
                  if (accepted.length === 0) return setErrors({ file: problems[0] })
                  setFile(picked)
                  setErrors({})
                }}
              />
              <div
                className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 transition-colors ${
                  errors.paper || errors.file ? bad : ok
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
              <ErrorText>{errors.file ?? errors.paper}</ErrorText>
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
            <div className="flex items-start justify-between gap-3">
              <div>
                <ErrorText>{errors.text}</ErrorText>
              </div>
              {/* Counter appears once you're close to the limit, and turns red past it. */}
              {text.length >= TEXT_LIMIT[kind] * 0.8 && (
                <span
                  className={`ml-auto shrink-0 pt-1 text-xs ${
                    text.length > TEXT_LIMIT[kind] ? 'text-kind-correction' : 'text-muted'
                  }`}
                >
                  {text.length.toLocaleString()} / {TEXT_LIMIT[kind].toLocaleString()}
                </span>
              )}
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={saving}
          className="mt-5 h-10 w-full rounded-xl bg-accent text-sm font-semibold text-accent-fg transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {saving ? 'Adding…' : 'Add'}
        </button>
      </form>
    </Modal>
  )
}
