import type { TaskRunStatus } from './types'

const TERMINAL: readonly TaskRunStatus[] = ['completed', 'completed_with_errors', 'failed', 'cancelled', 'interrupted', 'paused']

/** A requested stop or resource wait is still pending until the server confirms it. */
export const isTaskRunPending = (status: TaskRunStatus | undefined): boolean => status !== undefined && !TERMINAL.includes(status)
