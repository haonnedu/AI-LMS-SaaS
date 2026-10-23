// Job polling state machine: pure functions, no timers.
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export const POLL_INTERVAL_MS = 3000;
export const MAX_POLL_INTERVAL_MS = 15000;
export const isTerminal = (status: string) => status === "succeeded" || status === "failed" || status === "cancelled";
export const isActive = (status: string) => status === "queued" || status === "running";
/** Delay before the next poll; backs off after consecutive errors. */
export function nextDelay(consecutiveErrors: number): number {
  return Math.min(MAX_POLL_INTERVAL_MS, POLL_INTERVAL_MS * 2 ** Math.max(0, Math.min(consecutiveErrors, 4)));
}
/** Job ids that still need polling. */
export function pendingJobIds(jobs: Record<string, string>): string[] {
  return Object.entries(jobs).filter(([, status]) => isActive(status)).map(([id]) => id);
}
export type PollState = { statuses: Record<string, string>; errors: number };
export function applyPoll(state: PollState, results: { id: string; status?: string; failed?: boolean }[]): PollState {
  const statuses = { ...state.statuses };
  let anyFailure = false;
  for (const result of results) {
    if (result.failed || !result.status) { anyFailure = true; continue; }
    statuses[result.id] = result.status;
  }
  return { statuses, errors: anyFailure ? state.errors + 1 : 0 };
}
export function shouldContinue(state: PollState): boolean { return pendingJobIds(state.statuses).length > 0; }
