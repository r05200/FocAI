import { useMemo } from 'react'
import { useVaultStore } from '../store/vaultStore'
import type { Directive } from '../types'

// Hard-coded until wired up. To go live: `GET /api/vault/directives?person=` (list[Directive];
// omit `person` for everyone). Adding is `POST /api/vault/directives`, removing is `DELETE .../{id}`.
const PLACEHOLDER: Directive[] = [
  { id: 'dir_1', person: 'alice', text: 'Prefer optimizer changes over architecture changes.', created_at: 1759913700 },
  { id: 'dir_2', person: 'alice', text: 'Skip anything on speculative decoding; already covered.', created_at: 1759913800 },
  { id: 'dir_3', person: 'bob', text: 'Always report end-to-end latency, not just throughput.', created_at: 1759913900 },
  { id: 'dir_4', person: 'bob', text: 'Favour results that hold past 32k context.', created_at: 1759914000 },
]

// Directives from any of the given vaults (OR), newest first. To go live, either call
// `GET /api/vault/directives` once with no `person` and filter here, or once per vault.
export function useDirectivesIn(vaults: string[]): Directive[] {
  const added = useVaultStore((s) => s.addedDirectives)
  return useMemo(() => {
    const wanted = new Set(vaults)
    return [...PLACEHOLDER, ...added]
      .filter((d) => wanted.has(d.person))
      .sort((a, b) => b.created_at - a.created_at)
  }, [vaults, added])
}

export function useDirectives(person: string | null): Directive[] {
  const added = useVaultStore((s) => s.addedDirectives)
  return useMemo(
    () =>
      [...PLACEHOLDER, ...added]
        .filter((d) => !person || d.person === person)
        .sort((a, b) => b.created_at - a.created_at),
    [person, added],
  )
}
