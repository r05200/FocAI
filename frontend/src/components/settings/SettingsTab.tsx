import { SettingsIcon } from '../ui/Icons'

export default function SettingsTab() {
  return (
    <div className="grid h-full place-items-center text-center text-muted">
      <div className="flex flex-col items-center">
        <SettingsIcon width={32} height={32} />
        <h2 className="mt-3 mb-1 text-lg font-semibold text-fg">Settings</h2>
        <p>Not implemented yet.</p>
      </div>
    </div>
  )
}
