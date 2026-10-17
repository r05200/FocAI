// A node's log rebuilt from what the backend already saves: the node itself (scores, decision,
// result, tokens) and, when we have them, the run's events that mention it (status changes, vault
// searches, activity lines). Used until the backend serves real per-step logs.
import { formatScore } from './format'
import type { LogEntry, PrunerEvent, TreeNode } from '../types'

export function deriveNodeLogs(node: TreeNode, events: PrunerEvent[] = []): LogEntry[] {
  const out: LogEntry[] = []
  const add = (e: Omit<LogEntry, 'id'>) => out.push({ id: `${node.id}-${out.length}`, ...e })
  const t0 = node.created_at

  add({ ts: t0, kind: 'thought', title: `Proposed a ${node.type}`, text: node.description })

  const mine = events.filter(
    (e) => ('node' in e && e.node.id === node.id) || ('node_id' in e && e.node_id === node.id),
  )
  if (mine.length > 0) {
    for (const e of mine) {
      if (e.type === 'vault_retrieved') {
        add({ ts: e.ts, kind: 'tool_call', title: `Searched ${e.person}'s vault`, text: e.query, tool: 'search_vault', args: { query: e.query } })
        add({
          ts: e.ts,
          kind: 'tool_result',
          title: `${e.item_ids.length} note${e.item_ids.length === 1 ? '' : 's'} found`,
          text: e.item_ids.map((id, i) => `${id}  (similarity ${e.similarities[i]?.toFixed(2)})`).join('\n') || 'Nothing close enough.',
          tool: 'search_vault',
        })
      } else if (e.type === 'node_updated') {
        add({ ts: e.ts, kind: 'activity', title: `Status: ${e.change}`, text: '' })
      } else if (e.type === 'activity') {
        add({ ts: e.ts, kind: 'activity', title: e.message, text: '' })
      }
    }
  }

  if (node.pre_score) {
    const p = node.pre_score
    add({
      ts: t0 + 0.001,
      kind: 'decision',
      title: `Pre-score ${formatScore(p.overall)}`,
      text: `Plausible ${formatScore(p.plausible)} · relevant ${formatScore(p.relevant)} · novel ${formatScore(p.novel)}`,
    })
  }
  if (node.result) add({ ts: t0 + 0.002, kind: 'thought', title: 'Result', text: node.result })
  if (node.post_score !== null) add({ ts: t0 + 0.003, kind: 'decision', title: `Post-score ${formatScore(node.post_score)}`, text: '' })
  if (node.decision) {
    const d = node.decision
    add({
      ts: t0 + 0.004,
      kind: 'decision',
      title: `${d.verdict === 'keep' ? 'Kept' : 'Parked'} (${d.stage === 'human' ? 'by you' : `${d.stage}-scoring`})`,
      text: d.reason + (d.vault_items_used.length ? `\n\nVault notes used: ${d.vault_items_used.join(', ')}` : ''),
    })
  }
  if (node.tokens.total > 0) {
    add({ ts: t0 + 0.005, kind: 'activity', title: `${node.tokens.total.toLocaleString()} tokens`, text: `Agent ${node.tokens.agent.toLocaleString()} · scorer ${node.tokens.scorer.toLocaleString()}` })
  }
  return out.sort((a, b) => a.ts - b.ts)
}
