import { useEffect, useState, type ReactNode } from 'react'
import { MAP_LEAVE_MS } from '../../lib/cameraFly'
import { useRunStore } from '../../store/runStore'
import { useVaultStore } from '../../store/vaultStore'
import { TAB_ORDER, useUiStore, type TabId } from '../../store/uiStore'
import HistoryTab from '../history/HistoryTab'
import RunTab from '../run/RunTab'
import SettingsTab from '../settings/SettingsTab'
import VaultTab from '../vault/VaultTab'
import TabBar from './TabBar'

const VIEWS: Record<TabId, (active: boolean) => ReactNode> = {
  run: (active) => <RunTab active={active} />,
  history: (active) => <HistoryTab active={active} />,
  vault: (active) => <VaultTab active={active} />,
  settings: (active) => <SettingsTab active={active} />,
}

// FLAG (ignore unless asked): all tabs stay mounted, so two WebGL canvases exist at once; they pause when hidden.
// All views stay mounted and are stacked; switching tabs animates scale/opacity so moving
// down the sidebar feels like flying deeper (e.g. Research -> Vault zooms into the mind map).
// The switch dips to the background: the old view fades out first, and the new one only starts
// fading in once it's gone, so the two are never seen on top of each other.
const VIEW_STATE = {
  active: 'scale-100 opacity-100 duration-500 delay-300',
  before: 'pointer-events-none scale-125 opacity-0 blur-sm duration-300',
  after: 'pointer-events-none scale-30 opacity-0 blur-sm duration-300',
}

// Going from one mind map to another (the vault and a run's vault): the maps do the motion
// themselves (the old one dives in under a cover, the new one is revealed), so the views don't
// zoom or blur. The old view stays until its dive is over, then the two hand over quickly.
const MAP_SWITCH_STATE = {
  shown: 'scale-100 opacity-100 duration-200',
  hidden: 'pointer-events-none scale-100 opacity-0 duration-200',
}

// Research <-> History is a plain cut: they sit side by side in the sidebar, and zooming one away
// (History shrinking to a third on its way back to Research) only made the switch feel slow.
const DIRECT_STATE = {
  shown: 'scale-100 opacity-100 duration-0',
  hidden: 'pointer-events-none scale-100 opacity-0 duration-0',
}
const DIRECT_PAIR: TabId[] = ['run', 'history']

const RETRY_REMOTE_MS = 10_000

export default function AppShell() {
  const tab = useUiStore((s) => s.tab)
  const loadRemote = useVaultStore((s) => s.loadRemote)
  // Load the vaults, cards and directives from the backend at start, and keep trying every few
  // seconds while it can't be reached (so a backend started after the page is picked up).
  const remoteStatus = useVaultStore((s) => s.remote.status)
  useEffect(() => {
    void loadRemote()
  }, [loadRemote])
  useEffect(() => {
    if (remoteStatus !== 'offline') return
    const t = setInterval(() => void loadRemote(), RETRY_REMOTE_MS)
    return () => clearInterval(t)
  }, [remoteStatus, loadRemote])
  const activeIndex = TAB_ORDER.indexOf(tab)
  // Which tabs are showing a mind map: the vault, and Research while a run's vault is open.
  const runVaultShown = useRunStore((s) => s.runVaultOpen && s.viewingId !== null)
  const showsMap = (id: TabId) => id === 'vault' || (id === 'run' && runVaultShown)
  const [switched, setSwitched] = useState({ to: tab, from: tab })
  if (switched.to !== tab) setSwitched({ to: tab, from: switched.to })
  const mapSwitch = switched.from !== tab && showsMap(switched.from) && showsMap(tab)
  const direct = switched.from !== tab && DIRECT_PAIR.includes(switched.from) && DIRECT_PAIR.includes(tab)

  return (
    <div className="flex h-full">
      <TabBar />
      <main className="relative min-w-0 flex-1 overflow-hidden">
        {TAB_ORDER.map((id, i) => {
          const state = i === activeIndex ? 'active' : i < activeIndex ? 'before' : 'after'
          const involved = id === tab || id === switched.from
          const shownOrHidden = state === 'active' ? 'shown' : 'hidden'
          const look =
            direct && involved
              ? DIRECT_STATE[shownOrHidden]
              : mapSwitch && involved
                ? MAP_SWITCH_STATE[shownOrHidden]
                : VIEW_STATE[state]
          return (
            <section
              key={id}
              className={`absolute inset-0 origin-center transition-[transform,opacity,filter] ease-zoom motion-reduce:transform-none motion-reduce:blur-none ${look}`}
              style={mapSwitch && involved ? { transitionDelay: `${MAP_LEAVE_MS}ms` } : undefined}
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
