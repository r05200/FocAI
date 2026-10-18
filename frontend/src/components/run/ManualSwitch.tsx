// Manual mode switch: on, the agent waits for a person's say-so before each experiment instead of
// carrying on by itself. `error`: the backend refused the last flip (shown red, reason on hover).
export default function ManualSwitch({
  on,
  onToggle,
  disabled = false,
  error = null,
}: {
  on: boolean
  onToggle: () => void
  disabled?: boolean
  error?: string | null
}) {
  return (
    <label
      title={error ?? 'When on, the agent waits for your say-so instead of carrying on by itself'}
      className={`flex shrink-0 items-center gap-2 text-sm whitespace-nowrap select-none ${
        error ? 'text-kind-correction' : 'text-muted'
      } ${disabled ? 'opacity-50' : 'cursor-pointer'}`}
    >
      Manual mode
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label="Manual mode"
        disabled={disabled}
        onClick={onToggle}
        className={`flex h-4.5 w-8 shrink-0 items-center rounded-full p-0.5 transition-colors ${
          on ? 'bg-kind-paper' : 'bg-line'
        }`}
      >
        <span className={`size-3.5 rounded-full bg-white transition-transform ${on ? 'translate-x-3.5' : ''}`} />
      </button>
    </label>
  )
}
