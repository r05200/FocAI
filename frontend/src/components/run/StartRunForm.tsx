import { useEffect, useRef, useState, type ComponentType, type FormEvent, type KeyboardEvent, type SVGProps } from 'react'
import { ApiError, startRun } from '../../api/client'
import { useDirectivesIn } from '../../hooks/useDirectives'
import { useVaultPeople } from '../../hooks/useVaultGraph'
import { useRunStore } from '../../store/runStore'
import type { StartRunRequest } from '../../types'
import { ArrowUpIcon, CloseIcon, DirectiveIcon, FileIcon, FolderIcon, ImageIcon, PlusIcon, StopIcon } from '../ui/Icons'
import DirectivesPicker from './DirectivesPicker'

// FIXME(attachments): the attach options are a NON-FUNCTIONAL PLACEHOLDER. They're shown but
// disabled, so nothing can be attached and nothing is sent with the prompt. To build it:
//   1. enable the items below and add hidden <input type="file"> pickers;
//   2. reuse the checks already written in lib/attachments.ts (type, size, duplicates, limit);
//   3. send the attachments with POST /api/runs (the backend doesn't accept them yet);
//   4. folders are the unresolved part: a browser can't reveal a folder's real path, and
//      uploading a folder is wasteful when the backend can read the disk itself.
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
  const people = useVaultPeople()
  const pool = useDirectivesIn(dirVaults)
  const chosen = pool.filter((d) => dirIds.includes(d.id))
  const phase = useRunStore((s) => s.phase)
  const begin = useRunStore((s) => s.begin)
  const stop = useRunStore((s) => s.stop)
  const busy = phase !== 'idle'
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
    if (!prompt.trim()) return
    const body: StartRunRequest = {
      question: prompt.trim(),
      // TODO: there's no signed-in user yet; the first vault stands in for "me".
      primary_person: people[0],
      // The backend takes directive texts, not ids, and appends them to the prompts as-is.
      directives: chosen.map((d) => d.text),
    }
    setError(null)
    try {
      const run = await startRun(body)
      // TODO: open GET /api/runs/{id}/events with an AbortController and pass it to begin().
      begin(run.id)
    } catch (err) {
      // FIXME: start_run still returns 501, and the backend may not be running at all (network
      // error, or the dev proxy's 5xx). Fall back to a placeholder run so the UI (Stop button
      // etc.) can still be exercised. Remove this branch once runs are implemented.
      const unavailable = !(err instanceof ApiError) || err.status === 404 || err.status >= 500
      if (unavailable) begin('r_pending')
      else return setError(err instanceof Error ? err.message : 'Could not start the run.')
    }
    setPrompt('')
    if (textarea.current) textarea.current.style.height = 'auto'
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      // Enter sends; it never stops a run (too easy to hit by accident).
      if (!busy) e.currentTarget.form?.requestSubmit()
    }
  }

  function onInput(value: string) {
    setPrompt(value)
    const el = textarea.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = `${el.scrollHeight}px`
    }
  }

  return (
    <form onSubmit={onSubmit} className="w-full max-w-3xl">
      <div className="rounded-[26px] border border-line bg-elev p-2 shadow-lg shadow-black/10">
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
            placeholder="Ask a research question…"
            aria-label="Research question"
            onChange={(e) => onInput(e.target.value)}
            onKeyDown={onKeyDown}
            className="max-h-50 min-h-9 flex-1 resize-none bg-transparent py-1.5 leading-6 outline-none placeholder:text-muted"
          />

          <button
            type="submit"
            aria-label={busy ? 'Stop' : 'Send'}
            title={busy ? 'Stop the run' : 'Send'}
            disabled={phase === 'stopping' || (!busy && !prompt.trim())}
            className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-accent-fg disabled:opacity-30"
          >
            {busy ? <StopIcon /> : <ArrowUpIcon />}
          </button>
        </div>
      </div>
      {error && <p role="alert" className="mt-2 px-4 text-xs text-kind-correction">{error}</p>}
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
    </form>
  )
}
