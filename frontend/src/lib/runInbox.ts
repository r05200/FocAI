import type { ForkRequest, Suggestion, TreeNode } from '../types'

// What a run waits on a person for, shown in the notifications panel (RunCards).

// Manual mode: the proposals waiting on a choice (pending children of the awaiting nodes).
export function choiceNodes(nodes: readonly TreeNode[]): TreeNode[] {
  const waiting = new Set(nodes.filter((n) => n.awaiting_choice).map((n) => n.id))
  return nodes.filter((n) => n.parent_id !== null && waiting.has(n.parent_id) && n.status === 'pending')
}

// Open suggestions. A fork suggestion gets its own card (with the choices it needs), not a plain Confirm.
export const offeredSuggestions = (suggestions: readonly Suggestion[]) =>
  suggestions.filter((s) => s.status === 'open' && s.action !== 'fork')

// How many things wait on a person (the notification bell's badge): the fork to decide, the
// choices, and the suggestions.
export function pendingCount(nodes: readonly TreeNode[], suggestions: readonly Suggestion[], pendingFork: ForkRequest | null): number {
  return (pendingFork ? 1 : 0) + choiceNodes(nodes).length + offeredSuggestions(suggestions).length
}
