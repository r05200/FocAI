import { useMemo } from 'react'
import { useVaultStore } from '../store/vaultStore'
import { isSampleDirectiveTwin, SAMPLE_DIRECTIVES, sampleDirectiveKey } from '../fixtures/seed'
import type { Directive } from '../types'

// Every directive, newest first: the sample ones (src/fixtures/seed.ts), plus the backend's
// (GET /vault/directives, loaded once by the app shell) or, while it's unreachable, whatever was
// added locally. A sample the backend has its own copy of is shown as that copy only.
function useAllDirectives(): Directive[] {
  const { status, directives } = useVaultStore((s) => s.remote)
  const added = useVaultStore((s) => s.addedDirectives)
  const hidden = useVaultStore((s) => s.hiddenSampleDirectives)
  const seeded = useVaultStore((s) => s.seededSamples)
  return useMemo(() => {
    const live = status === 'ok' ? directives : added
    const samples = SAMPLE_DIRECTIVES.filter(
      (d) =>
        !hidden.includes(d.id) &&
        !live.some((r) => isSampleDirectiveTwin(d, r)) &&
        !(status === 'ok' && seeded.includes(sampleDirectiveKey(d))),
    )
    return [...samples, ...live].sort((a, b) => b.created_at - a.created_at)
  }, [status, directives, added, hidden, seeded])
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
