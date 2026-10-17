// Display formatting shared across views. Backend timestamps are epoch seconds.

// "Oct 17"
export function formatDate(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

// "Oct 17, 3:04 PM"
export function formatDateTime(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

// A 0..1 score on the 1-10 scale the UI shows: "7.3 / 10".
export function formatScore(score: number): string {
  return `${(score * 10).toFixed(1)} / 10`
}
