import { getConfig, isOffline, listPrompts } from '../../api/client'
import { usePolled } from '../../hooks/usePolled'
import type { PromptInfo, PublicConfig } from '../../types'

// Read-only view of the backend: its models, caps and score thresholds (GET /api/config) and the
// prompt templates it sends to the LLM (GET /api/prompts). Nothing here can be edited yet.

type Loaded<T> = { state: 'loading' } | { state: 'offline' } | { state: 'error'; message: string } | { state: 'ok'; data: T }

// Loaded each time the tab is opened; the previous answer stays up while it refreshes.
function useLoaded<T>(load: () => Promise<T>, active: boolean): Loaded<T> {
  const loaded = usePolled(active ? 'shown' : null, () =>
    load().then(
      (data): Loaded<T> => ({ state: 'ok', data }),
      (err): Loaded<T> =>
        isOffline(err) ? { state: 'offline' } : { state: 'error', message: err instanceof Error ? err.message : 'Failed to load' },
    ),
  )
  return loaded ?? { state: 'loading' }
}

const ROWS: { key: keyof PublicConfig; label: string; hint?: string }[] = [
  { key: 'fast_model', label: 'Fast model' },
  { key: 'strong_model', label: 'Strong model' },
  { key: 'vault_model', label: 'Vault model' },
  { key: 'embedding_model', label: 'Embedding model' },
  { key: 'max_depth', label: 'Max depth', hint: 'How deep the tree can go' },
  { key: 'branching', label: 'Branching', hint: 'Children proposed per node' },
  { key: 'node_budget', label: 'Node budget', hint: 'Nodes per run' },
  { key: 'pre_score_min', label: 'Pre-score minimum', hint: 'Below this a branch is parked before running (1 to 10)' },
  { key: 'run_score_min', label: 'Run-score minimum' },
  { key: 'post_score_min', label: 'Post-score minimum', hint: 'Below this a finished node is parked' },
  { key: 'rescore_park_below', label: 'Re-score park below' },
  { key: 'backtrack_below', label: 'Backtrack below' },
]

function Status({ s }: { s: Loaded<unknown> }) {
  if (s.state === 'loading') return <p className="text-sm text-muted">Loading…</p>
  if (s.state === 'offline') return <p className="text-sm text-kind-note">Backend unreachable.</p>
  if (s.state === 'error') return <p className="text-sm text-kind-correction">{s.message}</p>
  return null
}

function Prompt({ p }: { p: PromptInfo }) {
  return (
    <details className="group rounded-xl border border-line bg-elev">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm">
        <span className="font-medium">{p.name}</span>
        <span className="text-xs text-muted">
          {p.placeholders.length > 0 ? p.placeholders.map((x) => `{{${x}}}`).join(' ') : 'no placeholders'}
        </span>
      </summary>
      <pre className="max-h-80 overflow-auto border-t border-line px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap text-muted">
        {p.text}
      </pre>
    </details>
  )
}

export default function SettingsTab({ active }: { active: boolean }) {
  // Refetched each time the tab is opened.
  const config = useLoaded(getConfig, active)
  const prompts = useLoaded(listPrompts, active)

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-8">
        <h1 className="mb-1 text-2xl font-semibold">Settings</h1>
        <p className="mb-8 text-sm text-muted">What the backend is running with. Read-only for now.</p>

        <h2 className="mb-3 text-sm font-semibold">Models and limits</h2>
        <Status s={config} />
        {config.state === 'ok' && (
          <dl className="mb-10 divide-y divide-line rounded-xl border border-line bg-elev">
            {ROWS.map((r) => (
              <div key={r.key} className="flex items-baseline justify-between gap-6 px-4 py-2.5 text-sm">
                <dt>
                  {r.label}
                  {r.hint && <span className="ml-2 text-xs text-muted">{r.hint}</span>}
                </dt>
                <dd className="font-mono text-xs">{config.data[r.key]}</dd>
              </div>
            ))}
          </dl>
        )}

        <h2 className="mb-3 text-sm font-semibold">Prompts</h2>
        <Status s={prompts} />
        {prompts.state === 'ok' && (
          <div className="space-y-2 pb-8">
            {prompts.data.map((p) => (
              <Prompt key={p.name} p={p} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
