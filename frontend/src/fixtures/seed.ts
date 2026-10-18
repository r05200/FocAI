// Sample vault data (Alice and Bob, from the generated fixtures) that is shown in the vault no
// matter what the backend has, so the map always has something in it while the real vaults fill up.
// Backend data is shown alongside it. Set SEED_SAMPLE_DATA to false to turn all of this off.
import type { Directive } from '../types'
import { fixtureVaultGraph } from './index'

const SEED_SAMPLE_DATA = true

export const SAMPLE_GRAPH = SEED_SAMPLE_DATA ? fixtureVaultGraph : { nodes: [], edges: [] }

// Alice and Bob, in a fixed order (it fixes their colours).
export const SAMPLE_PEOPLE = [...new Set(SAMPLE_GRAPH.nodes.map((n) => n.person))].sort()

// Ids that exist only in the browser: the backend knows nothing about them.
export const SAMPLE_ITEM_IDS = new Set(SAMPLE_GRAPH.nodes.map((n) => n.id))

export const SAMPLE_DIRECTIVES: Directive[] = SEED_SAMPLE_DATA
  ? [
      { id: 'dir_1', person: 'alice', text: 'Prefer optimizer changes over architecture changes.', created_at: 1759913700 },
      { id: 'dir_2', person: 'alice', text: 'Skip anything on speculative decoding; already covered.', created_at: 1759913800 },
      { id: 'dir_3', person: 'bob', text: 'Always report end-to-end latency, not just throughput.', created_at: 1759913900 },
      { id: 'dir_4', person: 'bob', text: 'Favour results that hold past 32k context.', created_at: 1759914000 },
    ]
  : []
