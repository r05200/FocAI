import { useMemo } from 'react'
import { useVaultStore } from '../store/vaultStore'
import { SAMPLE_DIRECTIVES } from '../fixtures/seed'
import type { Directive } from '../types'

// Every directive, newest first: the sample ones (src/fixtures/seed.ts), plus the backend's
// (GET /vault/directives, loaded once by the app shell) or, while it's unreachable, whatever was
// added locally.
function useAllDirectives(): Directive[] {
  const { status, directives } = useVaultStore((s) => s.remote)
  const added = useVaultStore((s) => s.addedDirectives)
  const hidden = useVaultStore((s) => s.hiddenSampleDirectives)
  return useMemo(() => {
    const samples = SAMPLE_DIRECTIVES.filter((d) => !hidden.includes(d.id))
    return [...samples, ...(status === 'ok' ? directives : added)].sort((a, b) => b.created_at - a.created_at)
  }, [status, directives, added, hidden])
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
