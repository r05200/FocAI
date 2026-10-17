import { create } from 'zustand'
import type { Directive, VaultItemView } from '../types'

// 'select': drag rotates the map, click selects. 'pan': drag moves the map (also while Space is held).
export type VaultTool = 'select' | 'pan'

export type AddableKind = 'paper' | 'note' | 'question' | 'directive'

interface VaultState {
  // Whose vault is shown; null = the whole team.
  person: string | null
  setPerson: (person: string | null) => void
  selectedId: string | null
  select: (id: string | null) => void
  tool: VaultTool
  setTool: (tool: VaultTool) => void
  // Vaults created in this browser session, in creation order (see AddVault.tsx).
  addedPeople: string[]
  addPerson: (name: string) => void
  // Kinds a person can add by hand. The Add dialog remembers the last one picked.
  addKind: AddableKind
  setAddKind: (kind: AddableKind) => void
  // Added in this browser session only, until the backend calls exist (see AddKnowledge.tsx).
  addedItems: VaultItemView[]
  addedDirectives: Directive[]
  addItem: (item: VaultItemView) => void
  addDirective: (directive: Directive) => void
  directivesOpen: boolean
  setDirectivesOpen: (open: boolean) => void
}

export const useVaultStore = create<VaultState>()((set) => ({
  person: null,
  setPerson: (person) => set({ person, selectedId: null }),
  selectedId: null,
  select: (selectedId) => set({ selectedId }),
  tool: 'select',
  setTool: (tool) => set({ tool }),
  addedPeople: [],
  addPerson: (name) => set((s) => ({ addedPeople: [...s.addedPeople, name] })),
  addKind: 'paper',
  setAddKind: (addKind) => set({ addKind }),
  addedItems: [],
  addedDirectives: [],
  addItem: (item) => set((s) => ({ addedItems: [...s.addedItems, item] })),
  addDirective: (directive) => set((s) => ({ addedDirectives: [...s.addedDirectives, directive] })),
  directivesOpen: false,
  setDirectivesOpen: (directivesOpen) => set({ directivesOpen }),
}))
