import { useEffect, useState } from 'react'
import { fixtureSnapshot } from '../fixtures'
import { isOffline, listRuns } from '../api/client'
import type { Run } from '../types'

export interface RunHistory {
  runs: Run[]
  loading: boolean
  offline: boolean
}

// Every saved run, newest first (GET /api/runs); sample runs while the backend is unreachable.
// Refetched whenever `refreshKey` changes (e.g. when the History tab is opened).
export function useRunHistory(refreshKey: unknown): RunHistory {
  const [state, setState] = useState<RunHistory>({ runs: [], loading: true, offline: false })
  useEffect(() => {
    let cancelled = false
    listRuns()
      .then((runs) => !cancelled && setState({ runs, loading: false, offline: false }))
      .catch((err) => {
        if (cancelled) return
        if (!isOffline(err)) console.warn('Could not load run history:', err)
        setState({ runs: isOffline(err) ? [fixtureSnapshot.run] : [], loading: false, offline: isOffline(err) })
      })
    return () => {
      cancelled = true
    }
  }, [refreshKey])
  return state
}
