import { useState, type ReactNode } from 'react'
import { confirmSuggestion, dismissSuggestion, toggleInstruction } from '../../api/client'
import type { Overlay } from '../../hooks/useRunTree'
import type { ForkRequest, HumanAction, Instruction, Suggestion, TreeNode } from '../../types'
import { choiceNodes, offeredSuggestions } from '../../lib/runInbox'
import { ForkCard, UndoForkCard } from './ForkCard'

const ACTION_LABEL: Record<Suggestion['action'], string> = {
  run: 'Run next',
  expand: 'Explore from',
  restore: 'Restore',
  remeasure: 'Re-measure',
  fork: 'Fork from',
}

interface Props {
  runId: string
  suggestions: Suggestion[]
  instructions: Instruction[]
  nodes: TreeNode[]
  // The run is going and no fork waits on a decision (the backend refuses node actions, choices and
  // suggestions until then: 409). `live`: just the run going (the fork cards need only that).
  canAct: boolean
  live: boolean
  apply: (change: (o: Overlay) => void) => void // put what the backend returned on screen at once
  onFocusNode: (nodeId: string) => void
  // The fork waiting for a decision (Run.awaiting = "fork"), and the last confirmed one (for undo).
  pendingFork: ForkRequest | null
  lastFork: ForkRequest | null
  onForkChanged: (fork: ForkRequest) => void
  // Keep / park a node (Run this next / Drop it in manual mode); rejects with the backend's reason.
  onNodeAction: (nodeId: string, action: HumanAction) => Promise<void>
}

const errorText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback)

// The run's to-dos for a person, stacked in the notifications panel: the fork, the choices,
// suggestions for where to continue, and the steering instructions (chips that can be turned off).
// Each card only shows when it has something in it.
export default function RunCards({
  runId,
  suggestions,
  instructions,
  nodes,
  canAct,
  live,
  apply,
  onFocusNode,
  pendingFork,
  lastFork,
  onForkChanged,
  onNodeAction,
}: Props) {
  const choices = choiceNodes(nodes)
  const offered = offeredSuggestions(suggestions)
  const steering = instructions.filter((i) => i.kind === 'steer')
  if (!pendingFork && !lastFork && choices.length === 0 && offered.length === 0 && steering.length === 0) {
    return <p className="px-1 text-xs text-muted">Nothing needs you right now.</p>
  }
  const title = (id: string) => nodes.find((n) => n.id === id)?.description ?? id

  return (
    <div className="flex flex-col gap-2.5">
      {pendingFork && (
        <ForkCard
          key={pendingFork.id}
          runId={runId}
          fork={pendingFork}
          nodes={nodes}
          canAct={live}
          onChanged={onForkChanged}
          onFocusNode={onFocusNode}
        />
      )}
      {!pendingFork && lastFork && (
        <UndoForkCard key={lastFork.id} runId={runId} fork={lastFork} nodes={nodes} canAct={live} onChanged={onForkChanged} />
      )}

      {choices.length > 0 && (
        <Card title="Choose what runs next" tone="choice">
          <ul className="space-y-2">
            {choices.map((n) => (
              <ChoiceRow key={n.id} node={n} canAct={canAct} onFocusNode={onFocusNode} onNodeAction={onNodeAction} />
            ))}
          </ul>
        </Card>
      )}

      {offered.length > 0 && (
        <Card title="Suggested next steps">
          <ul className="space-y-2">
            {offered.map((s) => (
              <SuggestionRow
                key={s.id}
                runId={runId}
                suggestion={s}
                nodeTitle={title(s.node_id)}
                canAct={canAct}
                apply={apply}
                onFocusNode={onFocusNode}
              />
            ))}
          </ul>
        </Card>
      )}

      {steering.length > 0 && (
        <Card title="Your instructions">
          <ul className="space-y-1.5">
            {steering.map((i) => (
              <SteeringChip key={i.id} runId={runId} instruction={i} canAct={canAct} apply={apply} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

function Card({ title, tone = 'plain', children }: { title: string; tone?: 'plain' | 'choice'; children: ReactNode }) {
  return (
    <section
      aria-label={title}
      className={`pointer-events-auto rounded-xl border bg-elev px-3 py-2.5 text-sm shadow-lg shadow-black/20 ${
        tone === 'choice' ? 'border-kind-note' : 'border-line'
      }`}
    >
      <h3 className={`mb-1.5 text-xs font-semibold ${tone === 'choice' ? 'text-kind-note' : ''}`}>{title}</h3>
      {children}
    </section>
  )
}

// POST .../suggestions/{id}/confirm | dismiss.
function SuggestionRow({
  runId,
  suggestion: s,
  nodeTitle,
  canAct,
  apply,
  onFocusNode,
}: {
  runId: string
  suggestion: Suggestion
  nodeTitle: string
  canAct: boolean
  apply: Props['apply']
  onFocusNode: (nodeId: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function resolve(confirm: boolean) {
    setBusy(true)
    setError(null)
    try {
      const done = await (confirm ? confirmSuggestion : dismissSuggestion)(runId, s.id)
      apply((o) => o.suggestions.set(done.id, done))
    } catch (err) {
      setError(errorText(err, 'Could not do that.'))
    }
    setBusy(false)
  }

  return (
    <li className="rounded-lg bg-hover px-2.5 py-2">
      <button onClick={() => onFocusNode(s.node_id)} className="text-left hover:underline">
        <span className="font-medium">{ACTION_LABEL[s.action]}: </span>
        {nodeTitle}
      </button>
      {s.reason && <p className="mt-0.5 text-xs leading-relaxed text-muted">{s.reason}</p>}
      <div className="mt-1.5 flex gap-1.5">
        <button
          onClick={() => void resolve(true)}
          disabled={!canAct || busy}
          className="h-7 rounded-md bg-accent px-2.5 text-xs font-medium text-accent-fg disabled:opacity-50"
        >
          Confirm
        </button>
        <button
          onClick={() => void resolve(false)}
          disabled={!canAct || busy}
          className="h-7 rounded-md border border-line px-2.5 text-xs text-muted hover:text-fg disabled:opacity-50"
        >
          Dismiss
        </button>
      </div>
      {error && <p className="mt-1 text-xs text-kind-correction">{error}</p>}
    </li>
  )
}

// PATCH .../instructions/{id} {active}: an inactive instruction is left out of every prompt.
function SteeringChip({ runId, instruction: i, canAct, apply }: { runId: string; instruction: Instruction; canAct: boolean; apply: Props['apply'] }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const active = i.active !== false

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      const updated = await toggleInstruction(runId, i.id, !active)
      apply((o) => o.instructions.set(updated.id, updated))
    } catch (err) {
      setError(errorText(err, 'Could not change that.'))
    }
    setBusy(false)
  }

  return (
    <li>
      <div className="flex items-start gap-2">
        <button
          role="switch"
          aria-checked={active}
          aria-label={active ? 'Turn this instruction off' : 'Turn this instruction on'}
          disabled={!canAct || busy}
          onClick={() => void toggle()}
          className={`mt-0.5 flex h-4 w-7 shrink-0 items-center rounded-full p-0.5 transition-colors disabled:opacity-50 ${
            active ? 'bg-kind-paper' : 'bg-line'
          }`}
        >
          <span className={`size-3 rounded-full bg-white transition-transform ${active ? 'translate-x-3' : ''}`} />
        </button>
        <p className={`text-xs leading-relaxed [overflow-wrap:anywhere] ${active ? '' : 'text-muted line-through'}`}>{i.text}</p>
      </div>
      {error && <p className="mt-0.5 text-xs text-kind-correction">{error}</p>}
    </li>
  )
}

// One proposal the run waits on: "Run next" keeps it (it runs next), "Drop" parks it.
function ChoiceRow({
  node,
  canAct,
  onFocusNode,
  onNodeAction,
}: {
  node: TreeNode
  canAct: boolean
  onFocusNode: (nodeId: string) => void
  onNodeAction: Props['onNodeAction']
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function act(action: HumanAction) {
    setBusy(true)
    setError(null)
    try {
      await onNodeAction(node.id, action)
    } catch (err) {
      setError(errorText(err, 'Could not do that.'))
    }
    setBusy(false)
  }

  return (
    <li className="rounded-lg bg-hover px-2.5 py-2">
      <button onClick={() => onFocusNode(node.id)} className="text-left hover:underline">
        {node.revert_to && <span className="font-medium">Revert: </span>}
        {node.description}
      </button>
      {node.hypothesis?.statement && node.hypothesis.statement !== node.description && (
        <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted">{node.hypothesis.statement}</p>
      )}
      <div className="mt-1.5 flex gap-1.5">
        <button
          onClick={() => void act('keep')}
          disabled={!canAct || busy}
          className="h-7 rounded-md bg-accent px-2.5 text-xs font-medium text-accent-fg disabled:opacity-50"
        >
          Run next
        </button>
        <button
          onClick={() => void act('park')}
          disabled={!canAct || busy}
          className="h-7 rounded-md border border-line px-2.5 text-xs text-muted hover:text-fg disabled:opacity-50"
        >
          Drop
        </button>
      </div>
      {error && <p className="mt-1 text-xs text-kind-correction">{error}</p>}
    </li>
  )
}
