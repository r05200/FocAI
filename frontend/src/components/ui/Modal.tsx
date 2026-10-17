import { useEffect, useRef, type ReactNode } from 'react'
import { CloseIcon } from './Icons'

interface Props {
  title: string
  size?: 'md' | 'lg'
  onClose: () => void
  children: ReactNode
}

// Centered modal on a native <dialog>: focus trap, Escape to close, page behind goes inert.
// Mount it only while open; unmounting removes it.
export default function Modal({ title, size = 'md', onClose, children }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)

  // No cleanup: close() would fire onClose, and unmounting the element ends the modal anyway.
  useEffect(() => {
    const d = dialog.current
    if (!d || d.open) return
    d.showModal()
    // showModal focuses the first focusable thing, which is the header's close button. Start in
    // the first form field instead (mark one with data-autofocus to pick a different one).
    d.querySelector<HTMLElement>('[data-autofocus], input, textarea, select')?.focus()
  }, [])

  return (
    <dialog
      ref={dialog}
      aria-label={title}
      onClose={onClose}
      // A click on the backdrop lands on the <dialog> element itself.
      onClick={(e) => e.target === e.currentTarget && onClose()}
      className={`m-auto ${size === 'lg' ? 'w-[min(560px,calc(100%-32px))]' : 'w-[min(440px,calc(100%-32px))]'} rounded-2xl border border-line bg-elev p-0 text-fg shadow-2xl backdrop:bg-black/50`}
    >
      <div className="flex items-center justify-between px-5 pt-5 pb-4">
        <h2 className="text-base font-semibold">{title}</h2>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="grid size-8 place-items-center rounded-lg text-muted transition-colors hover:bg-hover hover:text-fg"
        >
          <CloseIcon />
        </button>
      </div>
      <div className="px-5 pb-5">{children}</div>
    </dialog>
  )
}
