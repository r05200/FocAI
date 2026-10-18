import { useEffect, useMemo, useRef, useState } from 'react'
import { selectRunning, useRunStore } from '../../store/runStore'
import { ArrowLeftIcon } from '../ui/Icons'
import RunVaultTab from '../runvault/RunVaultTab'
import StartRunForm from './StartRunForm'
import TreeCanvas from './TreeCanvas'

// The main menu's run list hugs its content (its widest question), up to this width; it keeps 32px
// (p-8) from the window edge and from the prompt bar.
const PANEL_MAX_W = 'clamp(210px, 19.5vw, 315px)'
const MENU_SETTLE_MS = 1200 // after going back, wait for the prompt bar to nearly arrive

// Research tab. Main menu: a centred prompt bar under a heading (plus, while runs are going, a
// list of them on the right). Once a run starts, the heading and hint fade out fast, the bar
// glides up to the top over 1.5s, and the tree view (a root node for now) appears below it.
// "Return to main menu" runs the same motion backwards; the run keeps going.
// How long the prompt bar takes to move between the middle and the top (its transition below).
const BAR_MOVE_MS = 1500

export default function RunTab({ active }: { active: boolean }) {
  const viewingId = useRunStore((s) => s.viewingId)
  const runs = useRunStore((s) => s.runs)
  const leave = useRunStore((s) => s.leave)
  const open = useRunStore((s) => s.open)
  const runVaultOpen = useRunStore((s) => s.runVaultOpen)
  const openRunVault = useRunStore((s) => s.openRunVault)
  const closeRunVault = useRunStore((s) => s.closeRunVault)
  const syncRuns = useRunStore((s) => s.syncRuns)
  const running = useMemo(() => selectRunning(runs), [runs])
  const started = viewingId !== null
  // The bar's text fades out while it moves between the middle and the top (BAR_MOVE_MS), then back
  // in: each move bumps `moves`, and `settled` catches up once the move is over.
  const [moves, setMoves] = useState(0)
  const [settled, setSettled] = useState(0)
  const [movedFor, setMovedFor] = useState(started)
  if (movedFor !== started) {
    setMovedFor(started)
    setMoves((m) => m + 1)
  }
  useEffect(() => {
    if (moves === 0) return
    const t = setTimeout(() => setSettled(moves), BAR_MOVE_MS)
    return () => clearTimeout(t)
  }, [moves])
  const barMoving = moves !== settled
  // The prompt bar is for a run that's still going (running or paused): a stopped or finished run
  // (e.g. opened from History) has nothing to send to, so the bar stays but is disabled.
  const viewedLife = runs.find((r) => r.id === viewingId)?.life
  const barDisabled = started && viewedLife === 'ended'

  // Learn about runs from the backend: once on arrival, then every few seconds while any run is
  // going (the live event stream isn't built, so polling GET /runs is how we notice a run ended).
  const anyRunning = running.length > 0
  useEffect(() => {
    void syncRuns()
    if (!anyRunning) return
    const t = setInterval(() => void syncRuns(), 4000)
    return () => clearInterval(t)
  }, [syncRuns, anyRunning])

  // The list's real width, so the prompt area can make exactly enough room for it.
  const panel = useRef<HTMLElement>(null)
  const [panelW, setPanelW] = useState(0)
  useEffect(() => {
    const el = panel.current
    if (!el) return
    const ro = new ResizeObserver(() => setPanelW(el.offsetWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const showList = !started && running.length > 0

  // Keep the tree mounted while it fades out after leaving, and remount it for each run so the
  // root node's pop-in plays again.
  const [treeId, setTreeId] = useState<string | null>(null)
  if (viewingId && viewingId !== treeId) setTreeId(viewingId)

  // Heading and hint: out in 250ms when a run starts; back in only once the bar is nearly home.
  const fade = (visible: boolean) =>
    `pointer-events-none absolute inset-x-0 transition-opacity ${
      visible ? 'opacity-100 duration-300 delay-[1200ms]' : 'opacity-0 duration-250'
    }`

  return (
    <div className="relative h-full overflow-hidden">
      {treeId && (
        <div
          key={treeId}
          className={`absolute inset-x-0 top-20 bottom-0 transition-opacity duration-300 ${
            started ? 'opacity-100' : 'opacity-0'
          }`}
          onTransitionEnd={(e) => {
            if (e.target === e.currentTarget && !useRunStore.getState().viewingId) setTreeId(null)
          }}
        >
          <TreeCanvas
            runId={treeId}
            question={runs.find((r) => r.id === treeId)?.question ?? ''}
            startedAt={(runs.find((r) => r.id === treeId)?.startedAt ?? 0) / 1000}
            active={active && !runVaultOpen}
            live={runs.some((r) => r.id === treeId && r.life !== 'ended')}
            onOpenRunVault={openRunVault}
          />
        </div>
      )}

      <button
        onClick={leave}
        // Out of reach while hidden (main menu) or covered by the run vault.
        inert={!started || runVaultOpen}
        className={`absolute top-5 left-6 z-20 flex items-center gap-1.5 text-sm text-muted transition-[opacity,color] hover:text-fg ${
          started ? 'opacity-100 delay-[1200ms] duration-300' : 'pointer-events-none opacity-0 duration-150'
        }`}
      >
        <ArrowLeftIcon />
        Return to main menu
      </button>

      {/* Everything but the run list lives in this area, which makes room for the list. It covers
          the whole tab, so it must let pointer events through to the tree underneath (only the
          prompt bar below opts back in). */}
      <div
        className="pointer-events-none absolute inset-y-0 left-0 transition-[right] duration-400 ease-out motion-reduce:duration-0"
        style={{
          right: showList ? panelW + 64 : 0,
          transitionDelay: showList ? `${MENU_SETTLE_MS}ms` : '0ms',
        }}
      >
        <h1
          className={`${fade(!started)} bottom-[calc(50%+56px)] text-center text-[28px] font-semibold`}
        >
          What should we research?
        </h1>
        <p className={`${fade(!started)} top-[calc(50%+44px)] text-center text-xs text-muted`}>
          Describe the question you want researched.
        </p>

        {/* The prompt bar: centred on the main menu, 16px from the top once a run is on screen. */}
        <div
          inert={barDisabled || runVaultOpen}
          className={`absolute left-1/2 z-10 w-full px-4 ${started ? 'max-w-[min(48rem,max(320px,calc(100%-400px)))]' : 'max-w-3xl'} transition-[top,transform,opacity] [transition-duration:1500ms,1500ms,300ms] ease-[cubic-bezier(0.65,0,0.35,1)] motion-reduce:duration-0 ${
            barDisabled ? 'pointer-events-none opacity-50' : 'pointer-events-auto'
          }`}
          style={{
            top: started ? 16 : '50%',
            transform: `translate(-50%, ${started ? '0%' : '-50%'})`,
          }}
        >
          <StartRunForm ended={barDisabled} textHidden={barMoving} />
        </div>
      </div>

      {/* This run's vault, over everything else (the tree keeps its place underneath). */}
      {runVaultOpen && viewingId && (
        <div className="absolute inset-0 z-30 animate-[fade-in_300ms_ease-out_both] bg-bg">
          <RunVaultTab
            runId={viewingId}
            active={active}
            live={runs.some((r) => r.id === viewingId && (r.life === 'running' || r.life === 'paused'))}
            onBack={closeRunVault}
          />
        </div>
      )}

      {/* Runs still going, shown on the main menu: scrollable, 32px from the window's edges. */}
      <aside
        ref={panel}
        aria-label="Current runs"
        aria-hidden={!showList}
        inert={!showList}
        className={`absolute top-8 right-8 bottom-8 w-max min-w-40 overflow-auto rounded-2xl border border-line bg-elev py-2 transition-opacity ${
          showList ? 'opacity-100 duration-300 delay-[1200ms]' : 'pointer-events-none opacity-0 duration-150'
        }`}
        style={{ maxWidth: PANEL_MAX_W }}
      >
        <p className="px-5 pt-3 pb-1 text-xs font-medium text-muted">Running · {running.length}</p>
        <ul>
          {running.map((r, i) => (
            <li key={r.id}>
              {/* The divider stops short of both edges. */}
              {i > 0 && <div className="mx-5 border-t border-line" />}
              <button
                onClick={() => open(r.id)}
                title="Open this run"
                className="block w-full px-5 py-3.5 text-left transition-colors hover:bg-hover"
              >
                <span className="flex items-start gap-2.5">
                  <span
                    className={`mt-1.5 size-2 shrink-0 rounded-full ${
                      r.life === 'paused' ? 'bg-kind-note' : 'animate-pulse bg-kind-learned'
                    }`}
                  />
                  <span className="min-w-0 text-sm leading-relaxed wrap-break-word">{r.question}</span>
                </span>
                {(r.life === 'stopping' || r.life === 'paused') && (
                  <span className="mt-1 block pl-4.5 text-xs text-muted">
                    {r.life === 'paused' ? 'Paused' : 'Stopping…'}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  )
}
