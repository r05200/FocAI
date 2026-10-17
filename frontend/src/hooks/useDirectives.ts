import { useMemo } from 'react'
import { useVaultStore } from '../store/vaultStore'
import type { Directive } from '../types'

// Sample directives, shown only while the backend is unreachable.
const SAMPLE: Directive[] = [
  { id: 'dir_1', person: 'alice', text: 'Prefer optimizer changes over architecture changes.', created_at: 1759913700 },
  { id: 'dir_2', person: 'alice', text: 'Skip anything on speculative decoding; already covered.', created_at: 1759913800 },
  { id: 'dir_3', person: 'bob', text: 'Always report end-to-end latency, not just throughput.', created_at: 1759913900 },
  { id: 'dir_4', person: 'bob', text: 'Favour results that hold past 32k context.', created_at: 1759914000 },
]

// Every directive, newest first: from the backend (GET /vault/directives, loaded once by the app
// shell), or the samples plus anything added locally while the backend is unreachable.
function useAllDirectives(): Directive[] {
  const { status, directives } = useVaultStore((s) => s.remote)
  const added = useVaultStore((s) => s.addedDirectives)
  return useMemo(
    () => [...(status === 'offline' ? [...SAMPLE, ...added] : directives)].sort((a, b) => b.created_at - a.created_at),
    [status, directives, added],
  )
}

// Directives from any of the given vaults (OR).
export function useDirectivesIn(vaults: string[]): Directive[] {
  const all = useAllDirectives()
  return useMemo(() => all.filter((d) => vaults.includes(d.person)), [all, vaults])
}

// One person's directives, or everyone's when `person` is null.
export function useDirectives(person: string | null): Directive[] {
  const all = useAllDirectives()
  return useMemo(() => all.filter((d) => !person || d.person === person), [all, person])
}
