import { useEffect } from 'react'
import { useVaultGraph, useVaultPeople } from '../../hooks/useVaultGraph'
import { personColor, RELATION_COLOR } from '../../lib/colors'
import { isViewOnly } from '../../lib/vaultAccess'
import { useVaultStore } from '../../store/vaultStore'
import type { VaultRelation } from '../../types'
import { DirectiveIcon, IdeasIcon, VaultIcon } from '../ui/Icons'
import AddKnowledge from './AddKnowledge'
import DirectivesPanel from './DirectivesPanel'
import VaultGraph from './VaultGraph'
import VaultItemPanel from './VaultItemPanel'
import { vaultName } from '../../lib/vaultName'

export default function VaultTab({ active }: { active: boolean }) {
  const people = useVaultPeople()
  const person = useVaultStore((s) => s.person)
  // The vault changes while runs go (learned and correction cards, items dropped when a fork is
  // undone): fetch it again every time the page is opened. Unchanged parts don't rebuild the map.
  const loadRemote = useVaultStore((s) => s.loadRemote)
  useEffect(() => {
    if (active) void loadRemote()
  }, [active, loadRemote])
  const directivesOpen = useVaultStore((s) => s.directivesOpen)
  const setDirectivesOpen = useVaultStore((s) => s.setDirectivesOpen)
  const { graph, status } = useVaultGraph(person)
  const shownPeople = person ? [person] : people
  const relations = [...new Set(graph.edges.map((e) => e.relation))] as VaultRelation[]
  // Which vault is shown is picked in the sidebar. Team and sample vaults can't be added to.
  const viewOnly = isViewOnly(person)
  // Without any vault there is nothing to draw: the 3D map is off.
  const loading = status === 'loading'
  const noVaults = !loading && people.length === 0

  return (
    // Graph area and the directives sidebar share the row; opening the sidebar narrows the map.
    <div className="flex h-full">
      <div className="relative min-w-0 flex-1">
        {!noVaults && !loading && <VaultGraph graph={graph} people={people} active={active} />}

        <header className="absolute top-4 left-5">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold">{vaultName(person)}</h1>
            {viewOnly ? (
              <span className="rounded-md border border-line px-1.5 py-0.5 text-xs text-muted">View only</span>
            ) : (
              // New entries go to the vault being viewed.
              <AddKnowledge author={person!} />
            )}
          </div>
          {!noVaults && (
            <p className="mt-1.5 pl-1 text-[13px] text-muted">
              {graph.nodes.length} items · {graph.edges.length} links
            </p>
          )}
          {status === 'offline' && (
            <p className="mt-1 pl-1 text-[13px] text-kind-note">
              Backend unreachable: showing sample data.{' '}
              <button onClick={() => void loadRemote()} className="underline hover:text-fg">
                Retry
              </button>
            </p>
          )}
        </header>

        {noVaults ? (
          <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
            <div className="flex flex-col items-center text-muted">
              <VaultIcon width={44} height={44} strokeWidth={1.4} />
              <p className="mt-4 text-lg font-semibold text-fg">No Vaults</p>
              <p className="mt-1 text-sm">Create one to get started</p>
            </div>
          </div>
        ) : null}

        {!noVaults && (
          <div className="absolute bottom-4 left-5 hidden max-w-md flex-wrap gap-x-3.5 gap-y-1 rounded-xl border border-line bg-elev px-3 py-2 text-xs text-muted sm:flex">
            {shownPeople.map((p) => (
              <span key={p} className="inline-flex items-center gap-1.5">
                <span className="size-2.5 rounded-full" style={{ background: personColor(people, p) }} />
                {vaultName(p)}
              </span>
            ))}
            {relations.map((r) => (
              <span key={r} className="inline-flex items-center gap-1.5 capitalize">
                <span className="w-4 border-t-2" style={{ borderColor: RELATION_COLOR[r] }} />
                {r}
              </span>
            ))}
          </div>
        )}

        <button
          aria-label="Directives"
          aria-pressed={directivesOpen}
          title="Directives"
          onClick={() => setDirectivesOpen(!directivesOpen)}
          className={`absolute top-4 right-5 grid size-9.5 place-items-center rounded-xl border transition-colors ${
            directivesOpen
              ? 'border-fg bg-hover text-fg'
              : 'border-line bg-elev text-muted hover:bg-hover hover:text-fg'
          }`}
        >
          <DirectiveIcon />
        </button>

        {/* TODO(REMOVE BEFORE SHIPPING): debugging only. Plays the card signal on the selected card
            (or a random one) to preview the effect. */}
        <button
          aria-label="Test card signal (debug)"
          title="Play the card signal (debug only, remove before shipping)"
          disabled={graph.nodes.length === 0}
          onClick={() => {
            const { selectedId, signalCard } = useVaultStore.getState()
            const item =
              graph.nodes.find((n) => n.id === selectedId) ?? graph.nodes[Math.floor(Math.random() * graph.nodes.length)]
            if (item) signalCard(item.id, personColor(people, item.person))
          }}
          className="absolute top-16 right-5 grid size-9.5 place-items-center rounded-xl border border-dashed border-kind-note bg-elev text-kind-note transition-colors hover:bg-hover disabled:opacity-40"
        >
          <IdeasIcon />
        </button>

        {!noVaults && graph.nodes.length === 0 && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center text-center text-muted">
            <div>
              <p className="font-medium text-fg">{vaultName(person)} is empty</p>
              {!viewOnly && <p className="mt-1 text-sm">Add a paper, note or question with the + button.</p>}
            </div>
          </div>
        )}

        <VaultItemPanel graph={graph} people={people} />
      </div>

      <DirectivesPanel people={people} />
    </div>
  )
}
