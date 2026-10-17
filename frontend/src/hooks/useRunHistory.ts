import { fixtureSnapshot } from '../fixtures'
import type { Run } from '../types'

// Hard-coded until wired up. To go live: `GET /api/runs` (list[Run]; not implemented in the
// backend yet) and return it here, newest first.
const EARLIER: Pick<Run, 'id' | 'question' | 'status' | 'mode' | 'primary_person' | 'created_at'>[] = [
  {
    id: 'r_prev2',
    question: 'Does 4-bit KV-cache quantization hurt long-context recall past 32k tokens?',
    status: 'done',
    mode: 'pruned',
    primary_person: 'alice',
    created_at: 1759913600,
  },
  {
    id: 'r_prev1',
    question: 'How do users perceive latency in agent interfaces compared with raw throughput?',
    status: 'failed',
    mode: 'unpruned',
    primary_person: 'bob',
    created_at: 1759827200,
  },
]

export type RunHistoryItem = (typeof EARLIER)[number]

export function useRunHistory(): RunHistoryItem[] {
  return [fixtureSnapshot.run, ...EARLIER].sort((a, b) => b.created_at - a.created_at)
}
