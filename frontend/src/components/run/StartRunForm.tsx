import { useEffect, useRef, useState, type ComponentType, type FormEvent, type KeyboardEvent, type SVGProps } from 'react'
import { addInstruction, createRunVault, isOffline, startRun } from '../../api/client'
import { useDirectivesIn } from '../../hooks/useDirectives'
import { useVaultPeople } from '../../hooks/useVaultGraph'
import { isLocalRun, newLocalRunId } from '../../lib/localRun'
import { useVaultStore } from '../../store/vaultStore'
import { selectPhase, useRunStore } from '../../store/runStore'
import type { StartRunRequest } from '../../types'
import { ArrowRightIcon, CloseIcon, DirectiveIcon, FileIcon, FolderIcon, ImageIcon, PauseIcon, PlayIcon, PlusIcon, StopIcon } from '../ui/Icons'
import DirectivesPicker from './DirectivesPicker'

// FIXME(attachments): the attach options are a NON-FUNCTIONAL PLACEHOLDER. They're shown but
// disabled, so nothing can be attached and nothing is sent with the prompt. To build it:
//   1. enable the items below and add hidden <input type="file"> pickers;
//   2. reuse the checks already written in lib/attachments.ts (type, size, duplicates, limit);
//   3. send the attachments with POST /api/runs (the backend doesn't accept them yet);
//   4. folders are the unresolved part: a browser can't reveal a folder's real path, and
//      uploading a folder is wasteful when the backend can read the disk itself.
// Stand-in run id until the backend creates runs (each placeholder run needs its own id).

const QUESTION_MIN = 3
const QUESTION_MAX = 2000

const OPTIONS: { label: string; hint: string; Icon: ComponentType<SVGProps<SVGSVGElement>> }[] = [
  { label: 'File', hint: 'PDF, Word, text, Markdown…', Icon: FileIcon },
  { label: 'Image', hint: 'PNG, JPG, GIF, WebP', Icon: ImageIcon },
  { label: 'Folder', hint: 'A folder on this machine', Icon: FolderIcon },
]

// Single-row prompt bar: [+ menu] [question] [send/stop]. The + spins into an × while its menu
// is open. "Directives" picks standing directives from one or more vaults; they show as a chip
// and are sent with the run. While a run is going, Send becomes Stop.
export default function StartRunForm() {
  const [prompt, setPrompt] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  // Kept between runs: directives are standing instructions, likely reused.
  const [dirVaults, setDirVaults] = useState<string[]>([])
  const [dirIds, setDirIds] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const people = useVaultPeople()
  // The run is scored against the primary person's vault, so prefer someone the backend knows (the
  // sample people, Alice and Bob, exist only in the browser).
  const backendPeople = useVaultStore((s) => s.remote.vaults)
  const pool = useDirectivesIn(dirVaults)
  const chosen = pool.filter((d) => dirIds.includes(d.id))
  const phase = useRunStore(selectPhase)
  const begin = useRunStore((s) => s.begin)
  const stop = useRunStore((s) => s.stop)
  const pause = useRunStore((s) => s.pause)
  const resume = useRunStore((s) => s.resume)
  const busy = phase !== 'idle'
  // Pause/Play shows once a run is going (and stays, disabled, while it's being stopped).
  const canHold = phase === 'running' || phase === 'paused'

  async function togglePause() {
    setError(null)
    try {
      await (phase === 'paused' ? resume() : pause())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change the run.')
    }
  }
  const textarea = useRef<HTMLTextAreaElement>(null)
  const menu = useRef<HTMLDivElement>(null)

  // Close the menu on outside click or Escape.
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (!menu.current?.contains(e.target as Node)) setMenuOpen(false)
    }
    const onKey = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && setMenuOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (busy) return void stop()
    const question = prompt.trim()
    if (!question) return
    if (question.length < QUESTION_MIN) return setError('Ask a fuller question (at least 3 characters).')
    if (question.length > QUESTION_MAX) {
      return setError(`Keep the question under ${QUESTION_MAX.toLocaleString()} characters (it’s ${question.length.toLocaleString()}).`)
    }
    // A run is scored against someone's vault, so at least one has to exist.
    if (people.length === 0) return setError('Create a vault first (Vault tab); runs are scored against it.')
    const body: StartRunRequest = {
      question,
      // TODO: there's no signed-in user yet; the first vault stands in for "me".
      primary_person: backendPeople[0]?.person ?? people[0],
      // The backend takes directive texts, not ids, and appends them to the prompts as-is.
      directives: chosen.map((d) => d.text),
    }
    setError(null)
    try {
      const run = await startRun(body)
      // TODO: open GET /api/runs/{id}/events with an AbortController and pass it to begin().
      begin(run.id, question)
      // Every run gets its own vault (the agent's discoveries), saved to disk with the run. Created
      // here as well as lazily by the backend; a backend without the route just says 404.
      createRunVault(run.id).catch((e) => console.debug('Run vault not created:', e))
    } catch (err) {
      // Backend not running at all: fall back to a placeholder run so the UI (Stop button, the run
      // list...) can still be exercised. Real backend errors are shown instead.
      if (isOffline(err)) begin(newLocalRunId(), question)
      else return setError(err instanceof Error ? err.message : 'Could not start the run.')
    }
    setPrompt('')
    if (textarea.current) textarea.current.style.height = 'auto'
  }

  // While a run is going, Enter sends what's typed as a further instruction to it
  // (POST /runs/{id}/instructions) instead of starting another run. The chosen directives replace
  // the run's directive list.
  async function sendInstruction() {
    const text = prompt.trim()
    const runId = useRunStore.getState().viewingId
    if (!text || !runId) return
    setError(null)
    try {
      if (!isLocalRun(runId)) await addInstruction(runId, { text, directives: chosen.map((d) => d.text) })
    } catch (err) {
      if (!isOffline(err)) return setError(err instanceof Error ? err.message : 'Could not send the instruction.')
    }
    setPrompt('')
    setNote('Instruction sent.')
    if (textarea.current) textarea.current.style.height = 'auto'
    setTimeout(() => setNote(null), 2500)
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      // Enter sends; it never stops a run (too easy to hit by accident). While a run is going it
      // sends an instruction to that run.
      if (!busy) e.currentTarget.form?.requestSubmit()
      else if (canHold) void sendInstruction()
    }
  }

  function onInput(value: string) {
    setPrompt(value)
    setError(null)
    const el = textarea.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = `${el.scrollHeight}px`
    }
  }

  return (
    <>
    <form onSubmit={onSubmit} className="w-full max-w-3xl">
      <div
        className={`rounded-[26px] border bg-elev p-2 shadow-lg shadow-black/10 transition-colors ${
          error ? 'border-kind-correction' : 'border-line'
        }`}
      >
        {chosen.length > 0 && (
          <div className="flex px-1 pt-1 pb-2">
            <span className="inline-flex h-8 items-center gap-1.5 rounded-xl bg-hover pr-1 pl-2.5 text-[13px]">
              <DirectiveIcon width={14} height={14} className="text-muted" />
              <button
                type="button"
                onClick={() => setPickerOpen(true)}
                title={chosen.map((d) => `• ${d.text}`).join('\n')}
                className="hover:underline"
              >
                {chosen.length} directive{chosen.length === 1 ? '' : 's'}
              </button>
              <button
                type="button"
                aria-label="Remove directives"
                onClick={() => setDirIds([])}
                className="grid size-6 place-items-center rounded-full text-muted hover:text-fg"
              >
                <CloseIcon />
              </button>
            </span>
          </div>
        )}
        <div className="flex items-end gap-2">
          {/* Attach menu (placeholder, see FIXME above) */}
          <div ref={menu} className="relative shrink-0">
            <button
              type="button"
              aria-label={menuOpen ? 'Close attach menu' : 'Attach'}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((o) => !o)}
              className={`grid size-9 place-items-center rounded-full transition-colors ${
                menuOpen ? 'bg-hover text-fg' : 'text-muted hover:bg-hover hover:text-fg'
              }`}
            >
              <PlusIcon
                width={18}
                height={18}
                className={`transition-transform duration-300 ease-zoom ${menuOpen ? 'rotate-[135deg]' : ''}`}
              />
            </button>
            {menuOpen && (
              <div
                role="menu"
                className="absolute top-full left-0 z-20 mt-2 w-60 rounded-xl border border-line bg-elev p-1.5 shadow-xl shadow-black/30"
              >
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false)
                    setPickerOpen(true)
                  }}
                  className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-hover"
                >
                  <DirectiveIcon width={16} height={16} className="shrink-0 text-muted" />
                  <span>
                    <span className="block text-sm">Directives</span>
                    <span className="block text-xs text-muted">Standing instructions from vaults</span>
                  </span>
                </button>
                <div className="my-1 border-t border-line" />
                {OPTIONS.map(({ label, hint, Icon }) => (
                  <button
                    key={label}
                    type="button"
                    role="menuitem"
                    disabled
                    title="Attachments aren't available yet"
                    className="flex w-full cursor-not-allowed items-center gap-3 rounded-lg px-2.5 py-2 text-left opacity-50"
                  >
                    <Icon className="shrink-0 text-muted" />
                    <span>
                      <span className="block text-sm">{label}</span>
                      <span className="block text-xs text-muted">{hint}</span>
                    </span>
                  </button>
                ))}
                <p className="px-2.5 pt-1.5 pb-1 text-xs text-muted">Attachments are coming soon.</p>
              </div>
            )}
          </div>

          <textarea
            ref={textarea}
            rows={1}
            value={prompt}
            placeholder={canHold ? 'Send an instruction to this run…' : 'Ask a research question…'}
            aria-label="Research question"
            onChange={(e) => onInput(e.target.value)}
            onKeyDown={onKeyDown}
            className="max-h-50 min-h-9 flex-1 resize-none bg-transparent py-1.5 leading-6 outline-none placeholder:text-muted"
          />

          {/* Pause / Play: only once a run is going. Stop (right) ends it for good. */}
          {busy && (
            <button
              type="button"
              aria-label={phase === 'paused' ? 'Resume' : 'Pause'}
              title={phase === 'paused' ? 'Resume the run' : 'Pause the run after its current step'}
              disabled={!canHold}
              onClick={() => void togglePause()}
              className="grid size-9 shrink-0 animate-[node-pop_300ms_var(--ease-zoom)_both] place-items-center rounded-full border border-line text-fg transition-colors hover:bg-hover disabled:opacity-30"
            >
              {phase === 'paused' ? <PlayIcon /> : <PauseIcon />}
            </button>
          )}

          <button
            type="submit"
            aria-label={busy ? 'Stop' : 'Send'}
            title={busy ? 'Stop the run' : 'Send'}
            disabled={phase === 'stopping' || (!busy && !prompt.trim())}
            className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-accent-fg disabled:opacity-30"
          >
            {busy ? <StopIcon /> : <ArrowRightIcon />}
          </button>
        </div>
      </div>
      {phase === 'paused' && !error && (
        <p className="mt-2 px-4 text-xs text-kind-note">Paused: the agent takes no further steps until you resume.</p>
      )}
      {note && !error && <p className="mt-2 px-4 text-xs text-muted">{note}</p>}
      {(error || prompt.length >= QUESTION_MAX * 0.9) && (
        <div className="mt-2 flex items-start justify-between gap-3 px-4 text-xs">
          <p role="alert" className="text-kind-correction">{error}</p>
          {/* Counter appears near the limit, red once over it. */}
          {prompt.length >= QUESTION_MAX * 0.9 && (
            <span className={`ml-auto shrink-0 ${prompt.length > QUESTION_MAX ? 'text-kind-correction' : 'text-muted'}`}>
              {prompt.length.toLocaleString()} / {QUESTION_MAX.toLocaleString()}
            </span>
          )}
        </div>
      )}
    </form>
    {/* Outside the <form> on purpose: a dialog is still a DOM child of it, so pressing Enter on one
        of the picker's checkboxes would "implicitly submit" the prompt (starting or stopping a run). */}
    {pickerOpen && (
      <DirectivesPicker
        vaults={dirVaults}
        selected={dirIds}
        onClose={() => setPickerOpen(false)}
        onApply={(vaults, ids) => {
          setDirVaults(vaults)
          setDirIds(ids)
          setPickerOpen(false)
        }}
      />
    )}
    </>
  )
}
