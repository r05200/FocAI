import type { VaultKind, VaultRelation } from '../types'

const KINDS: VaultKind[] = ['paper', 'note', 'question', 'correction', 'learned', 'directive']
const RELATIONS: VaultRelation[] = ['contradicts', 'supports', 'agrees', 'investigate']

// For DOM styles: CSS variables from the @theme block in index.css, so both themes stay in one
// place.
export const KIND_COLOR = Object.fromEntries(
  KINDS.map((k) => [k, `var(--color-kind-${k})`]),
) as Record<VaultKind, string>

export const RELATION_COLOR = Object.fromEntries(
  RELATIONS.map((r) => [r, `var(--color-rel-${r})`]),
) as Record<VaultRelation, string>

// Team members get a colour slot by their index in the sorted people list (wraps after 16).
export const PERSON_SLOTS = 16

export function personColor(people: string[], person: string): string {
  return `var(--color-person-${Math.max(people.indexOf(person), 0) % PERSON_SLOTS})`
}

// For canvas drawing, which can't resolve CSS variables: the same tokens, resolved now.
export interface Palette {
  bg: string
  elev: string
  line: string
  fg: string
  muted: string
  kind: Record<VaultKind, string>
  relation: Record<VaultRelation, string>
  person: string[]
}

export function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement)
  const v = (name: string) => css.getPropertyValue(`--color-${name}`).trim()
  return {
    bg: v('bg'),
    elev: v('elev'),
    line: v('line'),
    fg: v('fg'),
    muted: v('muted'),
    kind: Object.fromEntries(KINDS.map((k) => [k, v(`kind-${k}`)])) as Record<VaultKind, string>,
    relation: Object.fromEntries(RELATIONS.map((r) => [r, v(`rel-${r}`)])) as Record<
      VaultRelation,
      string
    >,
    person: Array.from({ length: PERSON_SLOTS }, (_, i) => v(`person-${i}`)),
  }
}

export function personSlot(palette: Palette, people: string[], person: string): string {
  return palette.person[Math.max(people.indexOf(person), 0) % PERSON_SLOTS]
}
