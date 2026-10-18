import type { LogSource } from '../../hooks/useNodeLogs'
import type { LogEntry, LogKind, TreeNode } from '../../types'
import { CloseIcon } from '../ui/Icons'

const KIND: Record<LogKind, { label: string; dot: string }> = {
  thought: { label: 'Thought', dot: 'bg-kind-question' },
  tool_call: { label: 'Tool call', dot: 'bg-kind-paper' },
  tool_result: { label: 'Tool result', dot: 'bg-kind-paper' },
  decision: { label: 'Decision', dot: 'bg-kind-note' },
  activity: { label: 'Activity', dot: 'bg-muted' },
  error: { label: 'Error', dot: 'bg-kind-correction' },
}

const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', second: '2-digit' })

interface Props {
  open: boolean
  node: TreeNode | null
  entries: LogEntry[]
  source: LogSource
  onClose: () => void
}

// Right-hand sidebar with a node's log: its reasoning, each tool call (with arguments) and result,
// and its scoring decisions, oldest first.
export default function NodeLogsPanel({ open, node, entries, source, onClose }: Props) {
  return (
    <aside
      aria-label="Node logs"
      aria-hidden={!open}
      inert={!open}
      // A flex sibling of the tree: opening it narrows the tree rather than covering it (and the
      // node's card with it).
      className={`shrink-0 overflow-hidden border-line bg-sidebar transition-[width] duration-300 ease-zoom ${
        open ? 'w-100 border-l' : 'w-0'
      }`}
    >
      <div className="flex h-full w-100 flex-col">
      <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-3">
        <div className="min-w-0">
          <h2 className="font-semibold">Logs</h2>
          <p className="truncate text-xs text-muted" title={node?.description}>
            {node?.description ?? ''}
          </p>
        </div>
        <button
          aria-label="Close logs"
          onClick={onClose}
          className="grid size-8 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-hover hover:text-fg"
        >
          <CloseIcon />
        </button>
      </header>

      <ol className="flex-1 overflow-auto px-4 pb-4">
        {source === 'loading' && <li className="py-6 text-center text-sm text-muted">Loading…</li>}
        {source !== 'loading' && entries.length === 0 && (
          <li className="py-6 text-center text-sm text-muted">Nothing logged yet.</li>
        )}
        {entries.map((e) => (
          <li key={e.id} className="relative border-l border-line pb-4 pl-5 last:pb-0">
            <span className={`absolute top-1.5 left-[-4.5px] size-2 rounded-full ${(KIND[e.kind] ?? KIND.activity).dot}`} />
            <p className="flex items-baseline justify-between gap-2 text-xs text-muted">
              <span>
                {(KIND[e.kind] ?? KIND.activity).label}
                {e.tool && <span className="font-mono"> · {e.tool}</span>}
              </span>
              <span className="shrink-0">{time(e.ts)}</span>
            </p>
            <p className="mt-0.5 text-sm font-medium">{e.title}</p>
            {/* A tool call's text is the reason the agent gave for making it: show it first. */}
            {e.kind === 'tool_call' && e.text && (
              <p className="mt-1 text-xs leading-relaxed text-fg">
                <span className="font-medium">Why: </span>
                {e.text}
              </p>
            )}
            {e.args && (
              <pre className="mt-1 overflow-auto rounded-md bg-bg px-2 py-1.5 font-mono text-[11px] text-muted">
                {JSON.stringify(e.args, null, 2)}
              </pre>
            )}
            {e.text && e.kind !== 'tool_call' && (
              <p
                className={`mt-1 text-xs leading-relaxed whitespace-pre-wrap text-muted ${
                  e.kind === 'tool_result' ? 'rounded-md bg-bg px-2 py-1.5 font-mono text-[11px]' : ''
                }`}
              >
                {e.text}
              </p>
            )}
          </li>
        ))}
      </ol>
      </div>
    </aside>
  )
}
