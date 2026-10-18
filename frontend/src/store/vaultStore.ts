import { create } from 'zustand'
import * as api from '../api/client'
import { SAMPLE_DIRECTIVES, SAMPLE_ITEM_IDS, SAMPLE_PEOPLE } from '../fixtures/seed'
import { isOffline } from '../api/client'
import type {
  Directive,
  IngestRequest,
  Position,
  VaultGraph,
  VaultItemView,
  VaultSummary,
} from '../types'

// 'select': drag rotates the map, click selects. 'pan': drag moves the map (also while Space is
// held). 'move': drag a card to a new spot (empty space still rotates).
export type VaultTool = 'select' | 'pan' | 'move'

export type AddableKind = 'paper' | 'note' | 'question' | 'directive'

// What the backend last told us. 'offline' means it couldn't be reached: the app then falls back to
// the sample data in src/fixtures plus anything added locally (the `added*` fields below).
export type RemoteStatus = 'loading' | 'ok' | 'offline'

interface Remote {
  status: RemoteStatus
  vaults: VaultSummary[]
  graph: VaultGraph // every vault's items and links
  directives: Directive[]
}

interface VaultState {
  // Whose vault is shown; null = the whole team.
  person: string | null
  setPerson: (person: string | null) => void
  selectedId: string | null
  select: (id: string | null) => void
  tool: VaultTool
  setTool: (tool: VaultTool) => void

  // ---- backend data (GET /vault/vaults, /vault/graph, /vault/directives)
  remote: Remote
  // People in the order they were first seen. It fixes each person's colour, so a vault created
  // later goes on the end instead of being re-sorted in (which would recolour everyone).
  peopleOrder: string[]
  // Sample directives the user deleted (they only exist in the browser).
  hiddenSampleDirectives: string[]
  loadRemote: () => Promise<void>
  // Mutations: call the backend and fold the result into `remote`. When the backend is
  // unreachable they fall back to the local-only data below, so the UI keeps working offline.
  createVault: (name: string) => Promise<void>
  ingest: (req: IngestRequest) => Promise<void>
  addDirective: (person: string, text: string) => Promise<void>
  removeDirective: (id: string) => Promise<void>
  moveCard: (id: string, position: Position) => Promise<void>
  relayout: () => Promise<void>

  // ---- local-only data, used while offline
  addedPeople: string[]
  addedItems: VaultItemView[]
  addedDirectives: Directive[]
  // Where cards were dragged to this session, by item id (read when the map is rebuilt).
  positions: Record<string, Position>

  // Kinds a person can add by hand. The Add dialog remembers the last one picked.
  addKind: AddableKind
  setAddKind: (kind: AddableKind) => void
  directivesOpen: boolean
  setDirectivesOpen: (open: boolean) => void
  // Ask the vault map to play a card's signal (border turns black, a line shoots up, then the
  // colour comes back), e.g. when the agent draws on it. `nonce` makes each request new.
  cardSignal: { nodeId: string; color: string; nonce: number } | null
  signalCard: (nodeId: string, color: string) => void
}

const EMPTY: Remote = { status: 'loading', vaults: [], graph: { nodes: [], edges: [] }, directives: [] }

const localId = () => `local_${Date.now()}`

// Add names we haven't seen yet to the end of the order (alphabetical among the new ones).
const withPeople = (order: string[], names: string[]) => [
  ...order,
  ...[...new Set(names)].filter((n) => !order.includes(n)).sort(),
]

// Writes made while the first load is still on its way wait for it, so they go to the backend
// when it's up instead of being kept locally (and then hidden once it answers).
async function settled(get: () => VaultState) {
  if (get().remote.status === 'loading') await get().loadRemote()
}

export const useVaultStore = create<VaultState>()((set, get) => ({
  person: null,
  setPerson: (person) => set({ person, selectedId: null }),
  selectedId: null,
  select: (selectedId) => set({ selectedId }),
  tool: 'select',
  setTool: (tool) => set({ tool }),

  remote: EMPTY,
  // The sample people go first, so Alice and Bob keep their colours whatever else turns up.
  peopleOrder: SAMPLE_PEOPLE,
  hiddenSampleDirectives: [],

  loadRemote: async () => {
    const [vaults, graph, directives] = await Promise.allSettled([
      api.listVaults(),
      api.getVaultGraph(),
      api.listDirectives(),
    ])
    const failed = [vaults, graph, directives].filter((r) => r.status === 'rejected').map((r) => r.reason)
    // Only an unreachable backend means offline (local-only writes). A real backend error on one
    // of the three is reported, and the rest still used: the backend is up, so writes go to it.
    if (failed.some((err) => isOffline(err))) {
      set((s) => ({ remote: { ...s.remote, status: 'offline' } }))
      return
    }
    for (const err of failed) console.warn('Could not load part of the vault:', err)
    set((s) => {
      const nextVaults = vaults.status === 'fulfilled' ? vaults.value : s.remote.vaults
      const nextGraph = graph.status === 'fulfilled' ? graph.value : s.remote.graph
      const nextDirectives = directives.status === 'fulfilled' ? directives.value : s.remote.directives
      const same = <T,>(a: T, b: T) => JSON.stringify(a) === JSON.stringify(b)
      const names = nextVaults.map((v) => v.person)
      return {
        remote: {
          status: 'ok',
          // Unchanged parts keep their object, so a refresh with nothing new doesn't rebuild the map.
          vaults: same(nextVaults, s.remote.vaults) ? s.remote.vaults : nextVaults,
          graph: same(nextGraph, s.remote.graph) ? s.remote.graph : nextGraph,
          directives: same(nextDirectives, s.remote.directives) ? s.remote.directives : nextDirectives,
        },
        peopleOrder: withPeople(s.peopleOrder, names),
        // The vault on screen may not exist on the backend (made while offline): back to the team.
        person: s.person && !SAMPLE_PEOPLE.includes(s.person) && !names.includes(s.person) ? null : s.person,
      }
    })
  },

  createVault: async (name) => {
    await settled(get)
    if (get().remote.status !== 'ok') {
      set((s) => ({ addedPeople: [...s.addedPeople, name], peopleOrder: withPeople(s.peopleOrder, [name]) }))
      return
    }
    // A 409 (already exists) or other API error is left for the dialog to show.
    const summary = await api.createVault({ person: name })
    set((s) => ({
      remote: { ...s.remote, vaults: [...s.remote.vaults, summary] },
      peopleOrder: withPeople(s.peopleOrder, [name]),
    }))
  },

  ingest: async (req) => {
    await settled(get)
    if (get().remote.status !== 'ok') return localIngest(req, set)
    const { item, edges } = await api.ingestItem(req) // 502 if the vault LLM fails: left for the dialog
    set((s) => ({
      remote: {
        ...s.remote,
        graph: { nodes: [...s.remote.graph.nodes, item], edges: [...s.remote.graph.edges, ...edges] },
        // Adding to a vault the backend didn't list yet creates it there.
        vaults: s.remote.vaults.some((v) => v.person === item.person)
          ? s.remote.vaults.map((v) => (v.person === item.person ? { ...v, item_count: v.item_count + 1 } : v))
          : [...s.remote.vaults, { person: item.person, item_count: 1 }],
      },
      peopleOrder: withPeople(s.peopleOrder, [item.person]),
    }))
  },

  addDirective: async (person, text) => {
    await settled(get)
    if (get().remote.status !== 'ok') {
      const d: Directive = { id: `dir_${localId()}`, person, text, created_at: Date.now() / 1000 }
      set((s) => ({ addedDirectives: [...s.addedDirectives, d] }))
      return
    }
    const d = await api.addDirective({ person, text })
    set((s) => ({ remote: { ...s.remote, directives: [...s.remote.directives, d] } }))
  },

  removeDirective: async (id) => {
    if (SAMPLE_DIRECTIVES.some((d) => d.id === id)) {
      set((s) => ({ hiddenSampleDirectives: [...s.hiddenSampleDirectives, id] }))
      return
    }
    if (get().remote.status !== 'ok') {
      set((s) => ({ addedDirectives: s.addedDirectives.filter((d) => d.id !== id) }))
      return
    }
    try {
      await api.deleteDirective(id)
    } catch (err) {
      if (!(err instanceof api.ApiError && err.status === 404)) throw err // 404: already gone
    }
    set((s) => ({ remote: { ...s.remote, directives: s.remote.directives.filter((d) => d.id !== id) } }))
  },

  // Called once per drop. The position is always kept for this session; the backend copy is best
  // effort (an unreachable backend just means it isn't persisted).
  moveCard: async (id, position) => {
    // Only the positions map changes: replacing the graph would rebuild the whole map and
    // reshuffle the other cards. The map reads positions whenever it is rebuilt for other reasons.
    set((s) => ({ positions: { ...s.positions, [id]: position } }))
    // Sample cards exist only in the browser; the backend has nothing to move.
    if (get().remote.status !== 'ok' || SAMPLE_ITEM_IDS.has(id)) return
    try {
      await api.moveItem(id, position)
    } catch (err) {
      if (!isOffline(err)) console.warn('Could not save the card position:', err)
    }
  },

  // Recompute the automatic layout (cards moved by hand keep their spot).
  relayout: async () => {
    if (get().remote.status !== 'ok') return
    const graph = await api.regenerateLayout({ reset_moved: false })
    set((s) => ({ remote: { ...s.remote, graph } }))
  },

  addedPeople: [],
  addedItems: [],
  addedDirectives: [],
  positions: {},

  addKind: 'paper',
  setAddKind: (addKind) => set({ addKind }),
  directivesOpen: false,
  setDirectivesOpen: (directivesOpen) => set({ directivesOpen }),
  cardSignal: null,
  signalCard: (nodeId, color) =>
    set((s) => ({ cardSignal: { nodeId, color, nonce: (s.cardSignal?.nonce ?? 0) + 1 } })),
}))

// Offline stand-in for POST /vault/items: a card with the text as its summary and no links.
function localIngest(req: IngestRequest, set: (fn: (s: VaultState) => Partial<VaultState>) => void) {
  const first = req.text.split('\n')[0]
  const item: VaultItemView = {
    id: localId(),
    person: req.person,
    kind: req.kind ?? 'note',
    title: req.title ?? (first.length > 60 ? `${first.slice(0, 59)}…` : first),
    summary: req.text,
    tags: [],
    source_text: req.text,
    investigate: false,
    retrieval_count: 0,
    created_at: Date.now() / 1000,
  }
  set((s) => ({ addedItems: [...s.addedItems, item] }))
}
