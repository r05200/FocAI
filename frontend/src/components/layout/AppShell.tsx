import type { ReactNode } from 'react'
import { TAB_ORDER, useUiStore, type TabId } from '../../store/uiStore'
import HistoryTab from '../history/HistoryTab'
import RunTab from '../run/RunTab'
import RunVaultTab from '../runvault/RunVaultTab'
import SettingsTab from '../settings/SettingsTab'
import VaultTab from '../vault/VaultTab'
import TabBar from './TabBar'

const VIEWS: Record<TabId, (active: boolean) => ReactNode> = {
  run: () => <RunTab />,
  history: () => <HistoryTab />,
  vault: (active) => <VaultTab active={active} />,
  runvault: (active) => <RunVaultTab active={active} />,
  settings: () => <SettingsTab />,
}

// All views stay mounted and are stacked; switching tabs animates scale/opacity so moving
// down the sidebar feels like flying deeper (e.g. Research -> Vault zooms into the mind map).
const VIEW_STATE = {
  active: 'scale-100 opacity-100',
  before: 'pointer-events-none scale-125 opacity-0 blur-sm',
  after: 'pointer-events-none scale-[0.3] opacity-0 blur-sm',
}

export default function AppShell() {
  const tab = useUiStore((s) => s.tab)
  const activeIndex = TAB_ORDER.indexOf(tab)

  return (
    <div className="flex h-full">
      <TabBar />
      <main className="relative min-w-0 flex-1 overflow-hidden">
        {TAB_ORDER.map((id, i) => {
          const state = i === activeIndex ? 'active' : i < activeIndex ? 'before' : 'after'
          return (
            <section
              key={id}
              className={`absolute inset-0 origin-center transition-[transform,opacity,filter] duration-700 ease-zoom motion-reduce:transform-none motion-reduce:blur-none ${VIEW_STATE[state]}`}
              aria-hidden={state !== 'active'}
              inert={state !== 'active'}
            >
              {VIEWS[id](state === 'active')}
            </section>
          )
        })}
      </main>
    </div>
  )
}
