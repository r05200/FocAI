import { useEffect, useEffectEvent, useState } from 'react'

interface Loaded<T> {
  key: string
  value: T
}

// Runs `load` whenever `key` changes (null: don't load), and again every `everyMs` while `poll` is
// true. Returns the latest result for the current key, or null until one arrives, so a new key
// never shows the previous one's data. A rejected load keeps whatever was there; a hook that wants
// a fallback instead resolves with it.
export function usePolled<T>(key: string | null, load: () => Promise<T>, poll = false, everyMs = 3000): T | null {
  const [loaded, setLoaded] = useState<Loaded<T> | null>(null)
  // Always calls the latest `load` without it being a dependency (it's usually an inline closure).
  const fetchLatest = useEffectEvent(() => load())

  useEffect(() => {
    if (key === null) return
    let cancelled = false
    const run = () =>
      fetchLatest().then(
        (value) => !cancelled && setLoaded({ key, value }),
        () => undefined,
      )
    void run()
    if (!poll) return () => void (cancelled = true)
    const t = setInterval(() => void run(), everyMs)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [key, poll, everyMs])

  return loaded && loaded.key === key ? loaded.value : null
}
