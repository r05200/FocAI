// Which vaults can be added to. Hardcoded for now: the team vault (everyone's items together) and
// the two sample people are view-only; every other vault belongs to "you" and can be added to.
// There's no sign-in yet, so there's nothing smarter to decide this from.
const VIEW_ONLY = ['alice', 'bob']

// `person` null is the team vault.
export const isViewOnly = (person: string | null): boolean => person === null || VIEW_ONLY.includes(person)

// People's vaults split for the sidebar, keeping the order given.
export function splitVaults(people: string[]): { yours: string[]; others: string[] } {
  return {
    yours: people.filter((p) => !isViewOnly(p)),
    others: people.filter((p) => isViewOnly(p)),
  }
}
