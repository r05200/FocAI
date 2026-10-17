// Runs that only exist in the browser: started while the backend was unreachable, so there's
// nothing on the backend to ask about them.

const LOCAL_PREFIX = 'r_pending'

export function newLocalRunId(): string {
  return `${LOCAL_PREFIX}_${Date.now()}`
}

export function isLocalRun(runId: string): boolean {
  return runId.startsWith(LOCAL_PREFIX)
}
