import { listForks } from '../api/client'
import { isLocalRun } from '../lib/localRun'
import type { ForkRequest } from '../types'
import { usePolled } from './usePolled'

// Where the amend-objectives agent asked to restart exploration (GET /runs/{id}/forks). Refetched
// every few seconds while `poll` is true: an instruction can add forks at any time. Failures (an
// unreachable backend, a run that only exists in the browser) just mean no forks are shown.
export function useForks(runId: string | null, enabled: boolean, poll: boolean): ForkRequest[] {
  const key = enabled && runId && !isLocalRun(runId) ? runId : null
  return usePolled(key, () => listForks(key!), poll) ?? []
}
