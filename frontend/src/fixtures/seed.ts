// Sample vault data (Alice and Bob, from the generated fixtures) that is shown in the vault no
// matter what the backend has, so the map always has something in it while the real vaults fill up.
// Backend data is shown alongside it. When the backend is up it is also given its own copy of the
// samples (vaultStore seedBackend); from then on that copy is shown instead of the browser's.
// Set SEED_SAMPLE_DATA to false to turn all of this off.
import type { Directive, VaultItemView } from '../types'
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

// The backend's copy of a sample has its own id, so it is recognised by what it says: the same
// person and title (a card) or the same person and text (a directive).
export const isSampleTwin = (sample: VaultItemView, item: VaultItemView) =>
  sample.person === item.person && sample.title === item.title
export const isSampleDirectiveTwin = (sample: Directive, d: Directive) =>
  sample.person === d.person && sample.text === d.text

// What vaultStore remembers about a sample once the backend has its copy (vaultStore
// seededSamples), so that copy can be deleted for good: it isn't copied again, and the browser's
// sample doesn't come back in its place.
export const sampleCardKey = (n: VaultItemView) => `card:${n.person}:${n.title}`
export const sampleDirectiveKey = (d: Directive) => `directive:${d.person}:${d.text}`
