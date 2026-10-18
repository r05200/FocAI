import { personColor, RELATION_COLOR } from '../../lib/colors'
import { missingSummary } from '../../lib/format'
import { displayTitle } from '../../lib/vaultGraphData'
import { useVaultStore } from '../../store/vaultStore'
import type { VaultGraph } from '../../types'
import DraggablePanel from '../ui/DraggablePanel'
import { vaultName } from '../../lib/vaultName'

export default function VaultItemPanel({ graph, people }: { graph: VaultGraph; people: string[] }) {
  const selectedId = useVaultStore((s) => s.selectedId)
  const select = useVaultStore((s) => s.select)
  const item = graph.nodes.find((n) => n.id === selectedId)
  if (!item) return null
  const title = (id: string) => displayTitle(graph.nodes.find((n) => n.id === id)?.title ?? id)
  const links = graph.edges.filter((e) => e.source === item.id || e.target === item.id)
  const missing = missingSummary(item.summary)

  return (
    <DraggablePanel
      aria-label="Vault item"
      onClose={() => select(null)}
      label={
        <>
          <span className="size-2.5 rounded-full" style={{ background: personColor(people, item.person) }} />
          {vaultName(item.person)} · {item.kind}
        </>
      }
    >
      <h3 className="mt-1.5 mb-2 font-semibold">{displayTitle(item.title)}</h3>
      {missing === null ? (
        <p className="mb-2.5 leading-relaxed text-muted">{item.summary}</p>
      ) : (
        // The backend couldn't read the link: say so plainly rather than as if it were a summary.
        <p className="mb-2.5 flex flex-wrap items-baseline gap-x-1.5 text-muted">
          <span className="rounded-md border border-line px-1.5 py-0.5 text-xs">No summary</span>
          {missing && <span className="text-xs">{missing}</span>}
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {item.tags.map((t) => (
          <span key={t} className="rounded-full bg-hover px-2 py-0.5 text-xs">
            {t}
          </span>
        ))}
      </div>
      {links.length > 0 && (
        <>
          <h3 className="mt-4 mb-2 font-semibold">Links</h3>
          {links.map((e) => (
            <p key={`${e.source}-${e.target}`} className="mb-2.5 leading-relaxed text-muted">
              <span className="font-semibold" style={{ color: RELATION_COLOR[e.relation] }}>
                {e.relation}
              </span>{' '}
              {title(e.source === item.id ? e.target : e.source)} — {e.reason}
            </p>
          ))}
        </>
      )}
    </DraggablePanel>
  )
}
