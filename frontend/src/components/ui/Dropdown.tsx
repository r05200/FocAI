import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { CheckIcon, ChevronDownIcon } from './Icons'

export interface DropdownOption {
  value: string
  label: string
  color?: string // CSS colour for the little dot
}

interface Props {
  value: string
  options: DropdownOption[]
  onChange: (value: string) => void
  'aria-label': string
}

// Self-styled select (a native <select> can't be themed): button + listbox popup that matches the
// app's other popups. Keyboard: Enter/Space/Arrows open; Arrows/Home/End move; Enter picks;
// Escape or Tab closes. Closes on an outside click.
export default function Dropdown({ value, options, onChange, 'aria-label': ariaLabel }: Props) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const id = useId()
  const selected = Math.max(options.findIndex((o) => o.value === value), 0)
  const current = options[selected]

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  function openMenu() {
    setActive(selected)
    setOpen(true)
  }

  function pick(i: number) {
    onChange(options[i].value)
    setOpen(false)
  }

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
        e.preventDefault()
        openMenu()
      }
      return
    }
    const last = options.length - 1
    if (e.key === 'ArrowDown') setActive((a) => Math.min(a + 1, last))
    else if (e.key === 'ArrowUp') setActive((a) => Math.max(a - 1, 0))
    else if (e.key === 'Home') setActive(0)
    else if (e.key === 'End') setActive(last)
    else if (e.key === 'Enter' || e.key === ' ') pick(active)
    else if (e.key === 'Escape' || e.key === 'Tab') return setOpen(false)
    else return
    e.preventDefault()
  }

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        role="combobox"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={onKeyDown}
        className="flex h-9.5 items-center gap-2 rounded-xl border border-line bg-elev pr-2.5 pl-3 text-base font-semibold capitalize transition-colors outline-none hover:bg-hover focus-visible:border-fg"
      >
        <span className="size-2.5 shrink-0 rounded-full" style={{ background: current.color ?? 'var(--color-muted)' }} />
        <span className="truncate">{current.label}</span>
        <ChevronDownIcon
          className={`ml-1 shrink-0 text-muted transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <ul
          id={`${id}-list`}
          role="listbox"
          aria-label={ariaLabel}
          className="absolute top-full left-0 z-30 mt-2 max-h-72 min-w-full overflow-auto rounded-xl border border-line bg-elev p-1.5 shadow-xl shadow-black/30"
        >
          {options.map((o, i) => (
            <li
              key={o.value}
              id={`${id}-${i}`}
              role="option"
              aria-selected={i === selected}
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(i)}
              className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm whitespace-nowrap capitalize ${
                i === active ? 'bg-hover' : ''
              }`}
            >
              <span className="size-2.5 shrink-0 rounded-full" style={{ background: o.color ?? 'var(--color-muted)' }} />
              <span className="flex-1">{o.label}</span>
              {i === selected && <CheckIcon className="shrink-0 text-muted" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
