import { useEffect, useState } from 'react'

export function isTyping(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))
  )
}

// Holding Space is the temporary Pan tool on the maps. Returns whether it's held.
//
// While `active` the Space key belongs to the map, full stop: it's swallowed before any focused
// control sees it. Otherwise Space would also press whatever button or dropdown was last clicked
// (a toolbar button, the vault dropdown...) and open or toggle it. It is left alone when typing in
// a field and while a dialog is open, where it should behave normally.
export function useSpacePan(active: boolean): boolean {
  const [held, setHeld] = useState(false)

  useEffect(() => {
    if (!active) return
    const mine = (e: KeyboardEvent) =>
      e.code === 'Space' && !e.metaKey && !e.ctrlKey && !e.altKey && !isTyping(e.target) && !document.querySelector('dialog[open]')
    const onKeyDown = (e: KeyboardEvent) => {
      if (!mine(e)) return
      e.preventDefault()
      e.stopPropagation() // capture phase: the focused control never gets it
      setHeld(true)
    }
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      // Browsers press a focused button on Space *keyup*, so swallow that too.
      if (mine(e)) {
        e.preventDefault()
        e.stopPropagation()
      }
      setHeld(false)
    }
    const release = () => setHeld(false)
    window.addEventListener('keydown', onKeyDown, { capture: true })
    window.addEventListener('keyup', onKeyUp, { capture: true })
    window.addEventListener('blur', release)
    return () => {
      window.removeEventListener('keydown', onKeyDown, { capture: true })
      window.removeEventListener('keyup', onKeyUp, { capture: true })
      window.removeEventListener('blur', release)
      setHeld(false)
    }
  }, [active])

  return held
}
