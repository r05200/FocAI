import { create } from 'zustand'

export type TabId = 'run' | 'history' | 'vault' | 'settings'

// Width of the collapsed sidebar rail (Tailwind w-16). The 3D maps size their canvas from it.
export const SIDEBAR_RAIL = 64

// Top-to-bottom sidebar order. It also drives the zoom direction between views:
// tabs earlier than the active one zoom past the camera, later ones wait far away.
export const TAB_ORDER: TabId[] = ['run', 'history', 'vault', 'settings']

// Tool for the run tree: 'select' (click or box-select nodes, drag nodes) or 'pan' (drag moves the
// view; also while Space is held).
export type TreeTool = 'select' | 'pan'

interface UiState {
  tab: TabId
  setTab: (tab: TabId) => void
  treeTool: TreeTool
  setTreeTool: (tool: TreeTool) => void
}

export const useUiStore = create<UiState>()((set) => ({
  tab: 'run',
  setTab: (tab) => set({ tab }),
  treeTool: 'select',
  setTreeTool: (treeTool) => set({ treeTool }),
}))
