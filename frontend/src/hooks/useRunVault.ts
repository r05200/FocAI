import { useMemo } from 'react'
import { getRunVault, isOffline } from '../api/client'
import { isLocalRun } from '../lib/localRun'
import type { RunIdea } from '../types'
import { usePolled } from './usePolled'

// Sample ideas for runs that only exist in the browser (backend unreachable), so the map can still
// be shown.
const SAMPLE_IDEAS: RunIdea[] = [
  { id: 'i1', branch: 'Quantization', title: '4-bit KV cache with per-channel scales', summary: 'Per-channel scaling keeps outliers from dominating the quantization error.' },
  { id: 'i2', branch: 'Quantization', title: 'Mixed precision: keep recent tokens in fp16', summary: 'Recent tokens matter most for recall; older ones tolerate lower precision.' },
  { id: 'i3', branch: 'Quantization', title: 'Calibrate on long-context data, not short prompts', summary: 'Short calibration sets under-represent the activation ranges seen past 32k.' },
  { id: 'i4', branch: 'Eviction', title: 'Heavy-hitter eviction by attention mass', summary: 'Drop tokens that rarely receive attention; keep the few that dominate.' },
  { id: 'i5', branch: 'Eviction', title: 'Sliding window plus attention sinks', summary: 'Keep the first few tokens and a recent window; surprisingly stable.' },
  { id: 'i6', branch: 'Eviction', title: 'Per-head eviction budgets', summary: 'Heads differ widely in how much context they use; give each its own budget.' },
  { id: 'i7', branch: 'Retrieval', title: 'Retrieve KV blocks instead of keeping them all', summary: 'Offload old blocks and fetch the relevant ones per query.' },
  { id: 'i8', branch: 'Retrieval', title: 'Cluster keys to cut lookup cost', summary: 'Index keys by cluster so retrieval touches a fraction of the cache.' },
  { id: 'i9', branch: 'Speculative decoding', title: 'Draft model shares the KV cache', summary: 'Sharing the cache removes the draft model’s memory overhead.' },
  { id: 'i10', branch: 'Speculative decoding', title: 'Tree-structured drafts for higher acceptance', summary: 'Verify several candidate continuations in one forward pass.' },
]

// 'unsupported': the backend answered but has no run vault (yet). 'offline': it couldn't be reached.
export type RunVaultStatus = 'loading' | 'ok' | 'unsupported' | 'offline'

export interface RunVaultState {
  ideas: RunIdea[]
  branches: string[]
  status: RunVaultStatus
}

interface Loaded {
  status: RunVaultStatus
  ideas: RunIdea[]
}

// A run's vault: what the agent itself discovered, by branch (GET /runs/{id}/vault). While `poll`
// is true it is refetched every few seconds, since the agent keeps adding to it as it explores.
export function useRunVault(runId: string | null, poll: boolean): RunVaultState {
  // A run that only exists in the browser has nothing on the backend to ask.
  const key = runId && !isLocalRun(runId) ? runId : null
  const loaded = usePolled(
    key,
    () =>
      getRunVault(key!).then(
        (v): Loaded => ({ status: 'ok', ideas: v.ideas }),
        // 404 from the backend: no such route (or run) yet. Anything unreachable: sample data.
        (err): Loaded =>
          isOffline(err) ? { status: 'offline', ideas: SAMPLE_IDEAS } : { status: 'unsupported', ideas: [] },
      ),
    poll,
    4000,
  )

  // Until this run's first answer arrives, show nothing rather than the previous run's ideas.
  const current: Loaded | null = runId && isLocalRun(runId) ? { status: 'offline', ideas: SAMPLE_IDEAS } : loaded
  const ideas = current?.ideas
  const branches = useMemo(() => [...new Set((ideas ?? []).map((i) => i.branch))], [ideas])
  return { ideas: ideas ?? [], branches, status: current?.status ?? 'loading' }
}
