import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { addInstruction, answerQuestion, createRunVault, isOffline, preflightRun, startRun } from '../../api/client'
import { useDirectivesIn } from '../../hooks/useDirectives'
import { useVaultPeople } from '../../hooks/useVaultGraph'
import { isLocalRun, newLocalRunId } from '../../lib/localRun'
import { SAMPLE_DIRECTIVES, SAMPLE_PEOPLE } from '../../fixtures/seed'
import { personColor } from '../../lib/colors'
import { useVaultStore } from '../../store/vaultStore'
import { selectPhase, useRunStore } from '../../store/runStore'
import type { ExecutionPlan, StartRunRequest } from '../../types'
import { ArrowRightIcon, CloseIcon, DirectiveIcon, FileIcon, PauseIcon, PlayIcon, PlusIcon, StopIcon } from '../ui/Icons'
import AddPathDialog from './AddPathDialog'
import Dropdown from '../ui/Dropdown'
import DirectivesPicker from './DirectivesPicker'
import { vaultName } from '../../lib/vaultName'

// Stand-in run id until the backend creates runs (each placeholder run needs its own id).

const SAMPLE_DIRECTIVE_IDS = new Set(SAMPLE_DIRECTIVES.map((d) => d.id))

// Dropdown value for "everyone's vaults" (never a real person: those match PERSON_PATTERN).
const TEAM = '__team'
// Dropdown value for "no vault": the run is scored without any, and its agent can't search one.
const NO_VAULT = '__none'
// Whose name a vault-less run is started under (the backend wants a person on every run). Never a
// real vault's owner: with no vault people, the backend's research searches the primary person's.
const NO_VAULT_PERSON = 'you'

const QUESTION_MIN = 3
const QUESTION_MAX = 2000
// The backend takes at most this many paths per run.
const PATHS_MAX = 50
// How long typing must pause before the preflight asks the backend (each ask is an LLM call).
const PREFLIGHT_DELAY_MS = 1200

// `at`: when the answer came (Date.now()), to tell whether it predates the files' last possible edit.
type Preflight =
  | { key: string; status: 'loading' }
  | { key: string; status: 'ok'; plan: ExecutionPlan; at: number }
  | { key: string; status: 'error'; error: string; at: number }
  | { key: string; status: 'offline'; at: number } // no backend (or no preflight route): nothing to say

const fileList = (files: string[]) => files.map((f) => `\`${f}\``).join(', ')

// Single-row prompt bar: [+ menu] [question] [send/stop]. The + spins into an × while its menu
// is open. "Directives" picks standing directives from one or more vaults; they show as a chip
// and are sent with the run. While a run is going, Send becomes Stop. `ended`: the run on screen
// is over (stopped or done), so the bar is shown disabled. `textHidden`: the bar is moving between
// the middle and the top; its text (or placeholder) fades out for the move and back in after.
export default function StartRunForm({ ended = false, textHidden = false }: { ended?: boolean; textHidden?: boolean }) {
  const prompt = useRunStore((s) => s.prompt)
  const setPrompt = useRunStore((s) => s.setPrompt)
  const [menuOpen, setMenuOpen] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  // Files the run works on (absolute paths, sent as `paths` when the run starts).
  const [paths, setPaths] = useState<string[]>([])
  const [pathOpen, setPathOpen] = useState(false)
  // The main menu's demo button hands over the paths to attach.
  const demoPaths = useRunStore((s) => s.demoPaths)
  useEffect(() => {
    if (!demoPaths) return
    setPaths(demoPaths)
    const vault = useRunStore.getState().demoVault
    if (vault) setVaultChoice(vault)
    useRunStore.getState().clearDemoPaths()
  }, [demoPaths])
  // Kept between runs: directives are standing instructions, likely reused.
  const [dirVaults, setDirVaults] = useState<string[]>([])
  const [dirIds, setDirIds] = useState<string[]>([])
  // The directive choice changed since the last send: only then is it sent with an instruction
  // (an empty list would replace, i.e. wipe, the run's directives).
  const [dirTouched, setDirTouched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  // A start or an instruction is on its way: further sends wait (no double runs on a double click).
  const [sending, setSending] = useState(false)
  const people = useVaultPeople()
  const pool = useDirectivesIn(dirVaults)
  const remoteUp = useVaultStore((s) => s.remote.status === 'ok')
  // The sample directives exist only in this browser: with the backend up they aren't sent.
  const chosen = pool.filter((d) => dirIds.includes(d.id) && !(remoteUp && SAMPLE_DIRECTIVE_IDS.has(d.id)))
  const phase = useRunStore(selectPhase)
  const begin = useRunStore((s) => s.begin)
  const stop = useRunStore((s) => s.stop)
  const pause = useRunStore((s) => s.pause)
  const resume = useRunStore((s) => s.resume)
  // The vault choice only exists on the main screen; once a run is open it's fixed.
  const onMainScreen = useRunStore((s) => s.viewingId === null)
  const [vaultChoice, setVaultChoice] = useState<string | null>(null)
  // The vaults a run can be scored against, in the order they were added. With the backend up, only
  // the ones it has (the sample Alice and Bob exist only in this browser, and the backend would
  // score against an empty vault); without it, the samples come after any made here.
  const remote = useVaultStore((s) => s.remote)
  const vaults =
    remote.status === 'ok'
      ? people.filter((p) => remote.vaults.some((v) => v.person === p))
      : [...people.filter((p) => !SAMPLE_PEOPLE.includes(p)), ...people.filter((p) => SAMPLE_PEOPLE.includes(p))]
  const vault =
    vaultChoice === NO_VAULT || vaultChoice === TEAM || (vaultChoice && vaults.includes(vaultChoice))
      ? vaultChoice
      : (vaults[0] ?? NO_VAULT)
  const busy = phase !== 'idle'
  // Pause/Play shows once a run is going (and stays, disabled, while it's being stopped).
  const canHold = phase === 'running' || phase === 'paused'

  // Preflight (main screen, with files attached): the backend's LLM reads the question and the files
  // for the execution order and the run command, and names the files the text needs that aren't
  // attached. Asked once typing pauses. Answers are kept by question/path set, so going back to one
  // already asked (e.g. undoing an edit) costs no second LLM call; a failed one is asked again.
  // The files' contents aren't in the key, so an answer from before the window last got focus
  // (the user may have edited a file elsewhere) is asked again; the old one shows until the new comes.
  const [preflights, setPreflights] = useState<Record<string, Preflight>>({})
  const setPreflight = (p: Preflight) => setPreflights((all) => ({ ...all, [p.key]: p }))
  const [focusedAt, setFocusedAt] = useState(0)
  useEffect(() => {
    const onFocus = () => setFocusedAt(Date.now())
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [])
  const preflightKey = onMainScreen && paths.length > 0 && prompt.trim().length >= QUESTION_MIN
    ? JSON.stringify([prompt.trim(), paths])
    : null
  const cachedPreflight = preflightKey ? preflights[preflightKey] : undefined
  const hasPreflight = !!cachedPreflight && cachedPreflight.status !== 'error'
    && cachedPreflight.status !== 'loading' && cachedPreflight.at >= focusedAt
  // An answer for another question/path set is never shown: until this one's comes, it's loading.
  const shownPreflight: Preflight | null = !preflightKey
    ? null
    : (cachedPreflight ?? { key: preflightKey, status: 'loading' })
  useEffect(() => {
    if (!preflightKey || hasPreflight) return
    const [question, files] = JSON.parse(preflightKey) as [string, string[]]
    let current = true
    const t = setTimeout(() => {
      preflightRun({ question, paths: files })
        .then((plan) => current && setPreflight({ key: preflightKey, status: 'ok', plan, at: Date.now() }))
        .catch((err) => {
          if (!current) return
          const at = Date.now()
          // No backend (or no preflight route): say nothing rather than a false warning.
          if (isOffline(err)) return setPreflight({ key: preflightKey, status: 'offline', at })
          setPreflight({ key: preflightKey, status: 'error', error: err instanceof Error ? err.message : String(err), at })
        })
    }, PREFLIGHT_DELAY_MS)
    return () => {
      current = false
      clearTimeout(t)
    }
  }, [preflightKey, hasPreflight, focusedAt])

  // In a run: its command state, published by its tree. The run waits on the "command" question
  // until it's answered; while it does, what's typed in the bar is that answer. One answered from
  // here is done with at once, not when the stream says so (Enter again would get a 409).
  const commandState = useRunStore((s) => (s.commandState?.runId === s.viewingId ? s.commandState : null))
  const [answered, setAnswered] = useState<string | null>(null) // `${runId} ${questionId}`
  const answeredHere = !!commandState?.question && answered === `${commandState.runId} ${commandState.question.id}`
  const commandQuestion = answeredHere ? null : (commandState?.question ?? null)
  async function togglePause() {
    setError(null)
    try {
      await (phase === 'paused' ? resume() : pause())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change the run.')
    }
  }
  const textarea = useRef<HTMLTextAreaElement>(null)
  // Fit the box to its text, also when the text is swapped from outside (a draft brought back).
  useEffect(() => {
    const el = textarea.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [prompt])
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
    if (busy) {
      setError(null)
      return void stop().catch((err) => setError(err instanceof Error ? err.message : 'Could not stop the run.'))
    }
    const question = prompt.trim()
    if (!question || sending) return
    if (question.length < QUESTION_MIN) return setError('Ask a fuller question (at least 3 characters).')
    if (question.length > QUESTION_MAX) {
      return setError(`Keep the question under ${QUESTION_MAX.toLocaleString()} characters (it’s ${question.length.toLocaleString()}).`)
    }
    setError(null)
    setSending(true)
    // The vault list may not have loaded yet (or the backend came up after the page): ask again
    // first, so a real run is never scored against the browser-only samples.
    if (useVaultStore.getState().remote.status !== 'ok') await useVaultStore.getState().loadRemote()
    const remoteNow = useVaultStore.getState().remote
    const usable = remoteNow.status === 'ok' ? vaults.filter((p) => remoteNow.vaults.some((v) => v.person === p)) : vaults
    const sendable = remoteNow.status === 'ok' ? remoteNow.vaults.map((v) => v.person) : usable
    const pool2 = usable.length ? usable : sendable
    // A run is scored against someone's vault, so at least one has to exist (unless it uses none).
    if (pool2.length === 0 && vault !== NO_VAULT) {
      setSending(false)
      return setError('Create a vault first (New vault in the sidebar); runs are scored against it.')
    }
    const picked =
      vault === NO_VAULT
        ? NO_VAULT_PERSON
        : vault && vault !== TEAM && pool2.includes(vault)
          ? vault
          : pool2[0]
    const body: StartRunRequest = {
      question,
      // Whose vault drives pruning: the one picked next to the + (the first vault until one is).
      // "Team vault" scores against everyone's vaults, with the first one as the primary.
      primary_person: picked,
      // "No vault": an empty list, so neither the scorers nor the agent's search read any vault.
      ...(vault === TEAM ? { vault_people: pool2 } : vault === NO_VAULT ? { vault_people: [] } : {}),
      // The backend takes directive texts, not ids, and appends them to the prompts as-is. The
      // browser-only sample directives aren't sent to a real backend.
      directives: chosen
        .filter((d) => !(remoteNow.status === 'ok' && SAMPLE_DIRECTIVE_IDS.has(d.id)))
        .map((d) => d.text),
      ...(paths.length > 0 ? { paths } : {}),
      // The main menu's manual mode switch, as it is now.
      manual: useRunStore.getState().draftManual,
    }
    try {
      const run = await startRun(body)
      // TODO: open GET /api/runs/{id}/events with an AbortController and pass it to begin().
      begin(run.id, question)
      setPaths([]) // they belonged to that run
      // Every run gets its own vault (the agent's discoveries), saved to disk with the run. Created
      // here as well as lazily by the backend; a backend without the route just says 404.
      createRunVault(run.id).catch((e) => console.debug('Run vault not created:', e))
    } catch (err) {
      // Backend not running at all: fall back to a placeholder run so the UI (Stop button, the run
      // list...) can still be exercised. Real backend errors are shown instead.
      if (isOffline(err)) {
        begin(newLocalRunId(), question)
        setPaths([])
      } else {
        setSending(false)
        return setError(err instanceof Error ? err.message : 'Could not start the run.')
      }
    }
    setSending(false)
    setDirTouched(false)
    setPrompt('')
    if (textarea.current) textarea.current.style.height = 'auto'
  }

  // While the run waits on its command question, Enter sends what's typed as the answer.
  async function sendCommand() {
    const text = prompt.trim()
    const runId = useRunStore.getState().viewingId
    if (!text || !commandQuestion || !runId || sending) return
    setError(null)
    setSending(true)
    try {
      await answerQuestion(runId, commandQuestion.id, text)
    } catch (err) {
      setSending(false)
      return setError(err instanceof Error ? err.message : 'Could not send the command.')
    }
    setSending(false)
    setAnswered(`${runId} ${commandQuestion.id}`)
    if (useRunStore.getState().viewingId === runId) setPrompt('')
    setNote('Command sent.')
    if (textarea.current) textarea.current.style.height = 'auto'
    setTimeout(() => setNote(null), 2500)
  }

  // While a run is going, Enter sends what's typed as a further instruction to it
  // (POST /runs/{id}/instructions) instead of starting another run. If the directive choice was
  // changed since the last send, it replaces the run's directive list; otherwise the run keeps its own.
  async function sendInstruction() {
    const text = prompt.trim()
    const runId = useRunStore.getState().viewingId
    if (!text || !runId || sending) return
    setError(null)
    setSending(true)
    try {
      if (!isLocalRun(runId)) {
        await addInstruction(runId, { text, ...(dirTouched ? { directives: chosen.map((d) => d.text) } : {}) })
      }
    } catch (err) {
      if (!isOffline(err)) {
        setSending(false)
        return setError(err instanceof Error ? err.message : 'Could not send the instruction.')
      }
    }
    setSending(false)
    setDirTouched(false)
    // Only if the run is still on screen: leaving it meanwhile put the main menu's draft back.
    if (useRunStore.getState().viewingId === runId) setPrompt('')
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
      else if (canHold) void (commandQuestion ? sendCommand() : sendInstruction())
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
        {(chosen.length > 0 || (onMainScreen && paths.length > 0)) && (
          <div className="flex flex-wrap gap-1.5 px-1 pt-1 pb-2">
            {/* File paths go with a new run, so they show on the main menu only. */}
            {onMainScreen && paths.map((p) => (
              <span key={p} className="inline-flex h-8 max-w-full items-center gap-1.5 rounded-xl bg-hover pr-1 pl-2.5 text-[13px]">
                <FileIcon width={14} height={14} className="shrink-0 text-muted" />
                <span className="min-w-0 truncate" title={p} dir="rtl">
                  <bdi>{p}</bdi>
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${p}`}
                  onClick={() => setPaths((ps) => ps.filter((o) => o !== p))}
                  className="grid size-6 shrink-0 place-items-center rounded-full text-muted hover:text-fg"
                >
                  <CloseIcon />
                </button>
              </span>
            ))}
            {chosen.length > 0 && (
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
                  onClick={() => {
                  setDirIds([])
                  setDirTouched(true)
                }}
                  className="grid size-6 place-items-center rounded-full text-muted hover:text-fg"
                >
                  <CloseIcon />
                </button>
              </span>
            )}
          </div>
        )}
        {/* Buttons stay vertically centred on the text, however many lines it runs to. */}
        <div className="flex items-center gap-2">
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
                className={`transition-transform duration-300 ease-zoom ${menuOpen ? 'rotate-135' : ''}`}
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
                {onMainScreen && <div className="my-1 border-t border-line" />}
                {/* Files go with the run when it starts, so the option is for the main screen only. */}
                {onMainScreen && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false)
                      setPathOpen(true)
                    }}
                    className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-hover"
                  >
                    <FileIcon className="shrink-0 text-muted" />
                    <span>
                      <span className="block text-sm">File path</span>
                      <span className="block text-xs text-muted">A file on this machine for the run to work on</span>
                    </span>
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Which vault the run is scored against. Main screen only. */}
          {onMainScreen && (
            <Dropdown
              compact
              aria-label="Vault for this run"
              value={vault}
              onChange={setVaultChoice}
              options={[
                ...(vaults.length > 0
                  ? [
                      { value: TEAM, label: vaultName(null) },
                      ...vaults.map((p) => ({ value: p, label: vaultName(p), color: personColor(people, p) })),
                    ]
                  : []),
                { value: NO_VAULT, label: 'No vault' },
              ]}
            />
          )}

          <textarea
            ref={textarea}
            rows={1}
            value={prompt}
            placeholder={
              ended
                ? 'This run has ended'
                : canHold && commandQuestion
                  ? 'Command that runs one experiment, e.g. uv run experiment.py'
                  : canHold
                    ? 'Send an instruction to this run…'
                    : 'Ask a research question…'
            }
            disabled={ended}
            aria-label="Research question"
            onChange={(e) => onInput(e.target.value)}
            onKeyDown={onKeyDown}
            className={`max-h-50 min-h-9 flex-1 resize-none bg-transparent py-1.5 leading-6 outline-none transition-opacity duration-300 placeholder:text-muted ${
              textHidden ? 'opacity-0' : ''
            }`}
          />

          {/* Shown while paused, to the right of the text; nothing while it's playing. */}
          {phase === 'paused' && (
            <span className="flex h-9 shrink-0 animate-[fade-in_200ms_ease-out_both] items-center gap-1.5 text-sm text-fg">
              <PauseIcon width={14} height={14} />
              Paused
            </span>
          )}

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
            disabled={phase === 'stopping' || (!busy && (!prompt.trim() || sending))}
            className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-accent-fg disabled:opacity-30"
          >
            {busy ? <StopIcon /> : <ArrowRightIcon />}
          </button>
        </div>
      </div>
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
    {/* Under the bar: what the backend read about running the experiments. In a run it's plain red
        text that fades in (the strip above the tree grows to fit it, see RunTab); a missing command
        is answered in the bar itself. */}
    {onMainScreen && shownPreflight && <PreflightNotice preflight={shownPreflight} />}
    {!onMainScreen && commandState && commandState.hasFiles && (() => {
      const { plan, commandKnown } = commandState
      const question = commandQuestion
      // No command: the run is asking for one, or the plan found none (e.g. a run that ended without).
      const unknown = !!question || (!!plan && !commandKnown && !answeredHere)
      const unreadable = plan?.unreadable ?? []
      const missing = plan?.missing_files ?? []
      if (!unknown && unreadable.length === 0 && missing.length === 0) return null
      return (
        <div className="mt-2 w-full max-w-3xl animate-[fade-in_400ms_ease-out_both] space-y-1 px-4 text-xs text-kind-correction">
          {unknown && (
            <p role="alert" className="font-medium">Execution commands unknown</p>
          )}
          {unreadable.length > 0 && <p>The agent couldn’t read {fileList(unreadable)} while forming hypotheses.</p>}
          {missing.length > 0 && <p>Named in your prompt or files but not attached: {fileList(missing)}.</p>}
        </div>
      )
    })()}
    {/* Outside the <form> on purpose: a dialog is still a DOM child of it, so pressing Enter on one
        of the picker's checkboxes would "implicitly submit" the prompt (starting or stopping a run). */}
    {pathOpen && (
      <AddPathDialog
        existing={paths}
        limit={PATHS_MAX}
        onAdd={(p) => {
          setPaths((ps) => [...ps, p])
          setPathOpen(false)
        }}
        onClose={() => setPathOpen(false)}
      />
    )}
    {pickerOpen && (
      <DirectivesPicker
        vaults={dirVaults}
        selected={dirIds}
        onClose={() => setPickerOpen(false)}
        onApply={(vaults, ids) => {
          setDirVaults(vaults)
          setDirIds(ids)
          setDirTouched(true)
          setPickerOpen(false)
        }}
      />
    )}
    </>
  )
}

// Main screen, files attached: the execution order the backend read, in red when the run command is
// unknown or the text names files that aren't attached (the run would stop to ask, or work blind).
function PreflightNotice({ preflight }: { preflight: Preflight }) {
  if (preflight.status === 'offline') return null
  if (preflight.status === 'loading') {
    return <p className="mt-2 px-4 text-xs text-muted">Reading the execution order from your prompt and files…</p>
  }
  if (preflight.status === 'error') {
    return <p className="mt-2 px-4 text-xs text-muted">Couldn’t read the execution order: {preflight.error}</p>
  }
  const { plan } = preflight
  return (
    <div className="mt-2 space-y-1 px-4 text-xs">
      {plan.command_known ? (
        <p className="text-muted">
          Run command: <code className="font-mono text-fg">{plan.run_command}</code>
        </p>
      ) : (
        <p role="alert" className="text-kind-correction">
          <span className="font-medium">Execution commands unknown</span>
          {plan.why ? ` (${plan.why})` : ''}. Write the command that runs one experiment in your prompt, or the run
          will not proceed.
        </p>
      )}
      {plan.missing_files.length > 0 && (
        <p className="text-kind-correction">
          Named in your prompt or files but not attached: {fileList(plan.missing_files)}. Attach them so the plan can
          read them.
        </p>
      )}
      {plan.steps.length > 0 && (
        <details className="text-muted">
          <summary className="cursor-pointer select-none hover:text-fg">Execution order ({plan.steps.length} steps)</summary>
          <ol className="mt-1 list-decimal space-y-0.5 pl-5">
            {plan.steps.map((s, i) => (
              <li key={i}>
                {s.purpose}
                {s.command && (
                  <>
                    {': '}
                    <code className={`font-mono ${s.verified ? 'text-fg' : 'text-kind-correction'}`}>{s.command}</code>
                    {!s.verified && ' (not found word for word)'}
                  </>
                )}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}
