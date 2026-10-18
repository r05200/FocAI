import { useEffect, useState } from 'react'
import { confirmFork, dismissFork, previewFork, undoFork } from '../../api/client'
import type { ForkRequest, ForkStep, TreeNode } from '../../types'

const errorText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback)
const ten = (score: number | null) => (score === null ? '–' : (score * 10).toFixed(1))

interface ForkCardProps {
  runId: string
  fork: ForkRequest // the one waiting for a decision (Run.awaiting = "fork")
  nodes: TreeNode[]
  canAct: boolean
  onChanged: (fork: ForkRequest) => void // the fork the backend returns after confirm / dismiss
  onFocusNode: (nodeId: string) => void
}

// The fork the amend agent suggests: restart from F, the deepest node the amended objectives still
// fit. Nothing changes until a person confirms. The slider moves F along the path (or below it);
// each move asks the backend what that F would park (GET .../preview?at=). Flagged off-path nodes
// (still relevant) are ticked "park anyway"; unticking keeps one live.
export function ForkCard({ runId, fork, nodes, canAct, onChanged, onFocusNode }: ForkCardProps) {
  // The choices for F, root first: the path to the suggested F, then the deeper options under it.
  const options: ForkStep[] = [...(fork.path ?? []), ...(fork.below ?? [])]
  const suggestedIndex = Math.max(options.findIndex((s) => s.node_id === fork.node_id), 0)
  const [index, setIndex] = useState(suggestedIndex)
  const at = options[index]?.node_id ?? fork.node_id
  // What F (as moved) would do. The suggestion itself already carries it for its own F.
  const [preview, setPreview] = useState<{ at: string; fork: ForkRequest } | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const current = at === fork.node_id ? fork : preview?.at === at ? preview.fork : null
  // Flagged nodes the person unticked: kept live.
  const [keepLive, setKeepLive] = useState<string[]>([])
  const [busy, setBusy] = useState<'confirm' | 'dismiss' | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (at === fork.node_id) return
    let cancelled = false
    // A short wait, so dragging the slider across several nodes asks only for where it stops.
    const t = setTimeout(() => {
      previewFork(runId, fork.id, at).then(
        (p) => !cancelled && setPreview({ at, fork: p }),
        (err) => !cancelled && setPreviewError(errorText(err, 'Could not preview that fork.')),
      )
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [runId, fork.id, fork.node_id, at])

  const title = (id: string) => options.find((s) => s.node_id === id)?.description ?? nodes.find((n) => n.id === id)?.description ?? id
  const parks = current?.park_ids?.length ?? 0
  const kept = current?.kept_overridden ?? 0
  const flagged = current?.flagged_ids ?? []
  const atRoot = index === 0

  async function resolve(confirm: boolean) {
    setBusy(confirm ? 'confirm' : 'dismiss')
    setError(null)
    try {
      const done = confirm
        ? await confirmFork(runId, fork.id, {
            at: at === fork.node_id ? null : at,
            keep_live: keepLive.filter((id) => flagged.includes(id)),
          })
        : await dismissFork(runId, fork.id)
      onChanged(done)
    } catch (err) {
      setError(errorText(err, 'Could not do that.'))
    }
    setBusy(null)
  }

  return (
    <section
      aria-label="Fork suggested"
      className="pointer-events-auto rounded-xl border border-kind-question bg-elev px-3 py-2.5 text-sm shadow-lg shadow-black/20"
    >
      <h3 className="mb-0.5 text-xs font-semibold text-kind-question">Fork suggested: waiting for your decision</h3>
      <p className="mb-2 text-xs leading-relaxed text-muted">{fork.reason}</p>

      {options.length > 1 && (
        <>
          <label className="mb-1 block text-xs text-muted" htmlFor={`fork-at-${fork.id}`}>
            Restart from
          </label>
          <input
            id={`fork-at-${fork.id}`}
            type="range"
            min={0}
            max={options.length - 1}
            step={1}
            value={index}
            disabled={!canAct || busy !== null}
            onChange={(e) => {
              setIndex(Number(e.target.value))
              setPreviewError(null)
            }}
            className="w-full accent-[var(--color-kind-question)]"
          />
        </>
      )}
      {/* The path with each node's relevance to the amended objectives (0-10). */}
      <ol className="mt-1 mb-2 space-y-0.5 text-xs">
        {options.map((s, i) => (
          <li key={s.node_id} className={`flex items-baseline gap-2 ${i === index ? 'font-semibold text-fg' : 'text-muted'}`}>
            <span className="w-7 shrink-0 text-right tabular-nums">{ten(s.score)}</span>
            <button onClick={() => onFocusNode(s.node_id)} className="min-w-0 truncate text-left hover:underline" title={s.description}>
              {s.description}
            </button>
            {i === suggestedIndex && <span className="shrink-0 text-[10px] text-kind-question">suggested</span>}
            {i > (fork.path?.length ?? 0) - 1 && <span className="shrink-0 text-[10px]">deeper</span>}
          </li>
        ))}
      </ol>

      {current ? (
        <p className="mb-2 text-xs leading-relaxed">
          Parks {parks} node{parks === 1 ? '' : 's'}
          {kept > 0 && (
            <span className="text-kind-note">
              , including {kept} you kept (the keep is cleared)
            </span>
          )}
          . New hypotheses grow from “{title(at)}”; the run is left paused.
        </p>
      ) : (
        <p className="mb-2 text-xs text-muted">{previewError ?? 'Working out what this would park…'}</p>
      )}
      {atRoot && (
        <p className="mb-2 text-xs text-kind-note">Forking at the root parks every branch: the run starts again from the baseline.</p>
      )}
      {current && current.web_search === false && (
        <p className="mb-2 text-xs text-muted">Web search isn’t set up, so the new hypotheses search the vault only.</p>
      )}

      {flagged.length > 0 && (
        <div className="mb-2">
          <p className="mb-1 text-xs text-muted">Still relevant, but off the path. Untick to keep one running:</p>
          <ul className="space-y-1">
            {flagged.map((id) => (
              <li key={id}>
                <label className="flex items-start gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={!keepLive.includes(id)}
                    disabled={!canAct || busy !== null}
                    onChange={(e) => setKeepLive((k) => (e.target.checked ? k.filter((x) => x !== id) : [...k, id]))}
                    className="mt-0.5 accent-[var(--color-kind-question)]"
                  />
                  <span>
                    Park anyway: <span className="text-muted">{title(id)}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex gap-1.5">
        <button
          onClick={() => void resolve(true)}
          disabled={!canAct || busy !== null || !current}
          className="h-7 rounded-md bg-accent px-2.5 text-xs font-medium text-accent-fg disabled:opacity-50"
        >
          {busy === 'confirm' ? 'Forking…' : 'Confirm fork'}
        </button>
        <button
          onClick={() => void resolve(false)}
          disabled={!canAct || busy !== null}
          className="h-7 rounded-md border border-line px-2.5 text-xs text-muted hover:text-fg disabled:opacity-50"
        >
          {busy === 'dismiss' ? 'Dismissing…' : 'Dismiss'}
        </button>
      </div>
      {error && <p className="mt-1 text-xs text-kind-correction">{error}</p>}
    </section>
  )
}

interface UndoCardProps {
  runId: string
  fork: ForkRequest // the latest confirmed fork
  nodes: TreeNode[]
  canAct: boolean
  onChanged: (fork: ForkRequest) => void
}

// The last fork, with "Undo fork": the tree goes back exactly as it was before it. If nodes were
// created since, the backend refuses (409, saying how many it would delete) until it's asked again
// with confirm_delete, so the second press is explicit.
export function UndoForkCard({ runId, fork, nodes, canAct, onChanged }: UndoCardProps) {
  const [busy, setBusy] = useState(false)
  // The backend's "Undo fork: this deletes N new node(s)..." once it has asked.
  const [needsConfirm, setNeedsConfirm] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const atId = fork.confirmed_at_node ?? fork.node_id
  const at = nodes.find((n) => n.id === atId)?.description ?? fork.path?.find((s) => s.node_id === atId)?.description ?? atId

  async function undo(confirmDelete: boolean) {
    setBusy(true)
    setError(null)
    try {
      onChanged(await undoFork(runId, fork.id, confirmDelete))
      setNeedsConfirm(null)
    } catch (err) {
      const message = errorText(err, 'Could not undo the fork.')
      if (!confirmDelete && /deletes \d+ new node/.test(message)) setNeedsConfirm(message)
      else setError(message)
    }
    setBusy(false)
  }

  return (
    <section
      aria-label="Last fork"
      className="pointer-events-auto rounded-xl border border-line bg-elev px-3 py-2.5 text-sm shadow-lg shadow-black/20"
    >
      <h3 className="mb-0.5 text-xs font-semibold">Forked at “{at}”</h3>
      <p className="mb-2 text-xs text-muted">The branches off that path were parked (they can be restored).</p>
      {needsConfirm ? (
        <>
          <p className="mb-2 text-xs text-kind-correction">{needsConfirm.replace(/ Send confirm_delete to go ahead\.?$/, '')}</p>
          <div className="flex gap-1.5">
            <button
              onClick={() => void undo(true)}
              disabled={!canAct || busy}
              className="h-7 rounded-md border border-kind-correction px-2.5 text-xs text-kind-correction hover:bg-kind-correction/10 disabled:opacity-50"
            >
              {busy ? 'Undoing…' : 'Delete them and undo'}
            </button>
            <button
              onClick={() => setNeedsConfirm(null)}
              disabled={busy}
              className="h-7 rounded-md border border-line px-2.5 text-xs text-muted hover:text-fg"
            >
              Keep the fork
            </button>
          </div>
        </>
      ) : (
        <button
          onClick={() => void undo(false)}
          disabled={!canAct || busy}
          className="h-7 rounded-md border border-line px-2.5 text-xs hover:bg-hover disabled:opacity-50"
        >
          {busy ? 'Undoing…' : 'Undo fork'}
        </button>
      )}
      {error && <p className="mt-1 text-xs text-kind-correction">{error}</p>}
    </section>
  )
}
