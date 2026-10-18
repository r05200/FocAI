import { useEffect, useState } from 'react'

// False until `ms` have passed since mounting (at once when `ms` is 0 or less).
export function useAfter(ms: number): boolean {
  const [ready, setReady] = useState(ms <= 0)
  useEffect(() => {
    if (ms <= 0) return
    const t = setTimeout(() => setReady(true), ms)
    return () => clearTimeout(t)
  }, [ms])
  return ready
}
