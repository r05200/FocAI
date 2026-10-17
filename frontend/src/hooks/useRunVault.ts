import { useMemo } from 'react'

// One thing the agent came up with or found while exploring, filed under the branch (tree path)
// it came from. Not a vault item: no owner, no embedding, no links.
export interface RunIdea {
  id: string
  branch: string
  title: string
  summary: string
}

// Hard-coded placeholder until runs and branches exist. To go live, derive these from the run's
// tree nodes (RunSnapshot.nodes): one idea per node, `branch` = the path from the root.
// FLAG (ignore unless asked): hard-coded ideas; no run tree is derived yet.
const PLACEHOLDER: RunIdea[] = [
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

export function useRunVault() {
  return useMemo(() => {
    const branches = [...new Set(PLACEHOLDER.map((i) => i.branch))]
    return { ideas: PLACEHOLDER, branches }
  }, [])
}
