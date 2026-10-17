import type { ComponentType, SVGProps } from 'react'
import { useUiStore, type TabId } from '../../store/uiStore'
import { ChatIcon, HistoryIcon, IdeasIcon, SettingsIcon, VaultIcon } from '../ui/Icons'

const TABS: Record<TabId, { label: string; Icon: ComponentType<SVGProps<SVGSVGElement>> }> = {
  run: { label: 'Research', Icon: ChatIcon },
  history: { label: 'History', Icon: HistoryIcon },
  vault: { label: 'Vault', Icon: VaultIcon },
  runvault: { label: 'Run vault', Icon: IdeasIcon },
  settings: { label: 'Settings', Icon: SettingsIcon },
}

// Labels fade in only while the sidebar is expanded (hover, or keyboard focus inside it; plain
// focus-within would keep it open after a mouse click leaves focus on a tab).
const LABEL = 'whitespace-nowrap opacity-0 transition-opacity duration-200 group-hover/nav:opacity-100 group-has-[:focus-visible]/nav:opacity-100'

function Tab({ id }: { id: TabId }) {
  const active = useUiStore((s) => s.tab === id)
  const setTab = useUiStore((s) => s.setTab)
  const { label, Icon } = TABS[id]
  return (
    <button
      role="tab"
      aria-selected={active}
      aria-label={label}
      onClick={(e) => {
        setTab(id)
        // A mouse click leaves focus on this button, and the next key press (e.g. a map shortcut
        // like M or Space) makes that focus "visible", which pops the sidebar open and shifts
        // the page. Let go of focus after mouse clicks; keyboard activation (detail 0) keeps it.
        if (e.detail > 0) e.currentTarget.blur()
      }}
      className={`flex h-11 w-full items-center gap-3 overflow-hidden rounded-xl px-3.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
        active ? 'bg-elev text-fg' : 'text-muted hover:bg-hover hover:text-fg'
      }`}
    >
      <Icon className="shrink-0" />
      <span className={LABEL}>{label}</span>
    </button>
  )
}

// Collapsed to an icon rail; hovering widens it. It's a flex sibling of the page, so the page
// shrinks to make room (nothing gets covered). Research, History, Vault and Run vault sit at the top, Settings at the bottom.
export default function TabBar() {
  return (
    <nav
      role="tablist"
      aria-orientation="vertical"
      className="group/nav z-30 flex w-16 shrink-0 flex-col gap-1 overflow-hidden border-r border-line bg-sidebar px-2 py-3 transition-[width] duration-200 ease-out hover:w-56 has-[:focus-visible]:w-56"
    >
      <div className="mb-2 flex h-10 items-center gap-3 px-3.5" aria-hidden="true">
        <span className="w-5 shrink-0 text-center text-lg font-bold">P</span>
        <span className={`font-semibold ${LABEL}`}>Pruner</span>
      </div>
      <Tab id="run" />
      <Tab id="history" />
      <Tab id="vault" />
      <Tab id="runvault" />
      <div className="mt-auto" />
      <Tab id="settings" />
    </nav>
  )
}
