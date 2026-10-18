// A vault's name on screen. The backend only takes a short lowercase id (PERSON_PATTERN: letters,
// numbers, - and _, no spaces), so what a person types has its spaces swapped for hyphens (vaultId)
// and the name shown is rebuilt from that id (vaultName).

export const TEAM_VAULT_NAME = 'Team Vault'

// The two sample vaults keep their proper names (the id alone can't give "Alice's Vault").
const SAMPLE_NAMES: Record<string, string> = { alice: 'Alice’s Vault', bob: 'Bob’s Vault' }

// What was typed as an id: trimmed, lowercase, spaces become hyphens.
export const vaultId = (typed: string) => typed.trim().toLowerCase().replace(/\s+/g, '-')

// The name to show for a vault id; null is the team vault.
export function vaultName(person: string | null): string {
  if (person === null) return TEAM_VAULT_NAME
  const sample = SAMPLE_NAMES[person]
  if (sample) return sample
  return person
    .split(/[-_]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ')
}
