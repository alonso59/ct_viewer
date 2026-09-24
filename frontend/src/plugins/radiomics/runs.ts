// Run status helpers (RAD-06, RADIOMICS §Run lifecycle)
import type { Job } from '../../api'
import type { RunStatus, RunSummary } from './model/types'

export const RUN_TONE: Record<RunStatus, string | undefined> = {
  queued: undefined,
  running: 'accent',
  completed: 'ok',
  completed_with_errors: 'warn',
  failed: 'error',
  cancelled: undefined,
  interrupted: 'warn',
}

export const ACTIVE: RunStatus[] = ['queued', 'running']
/** RAD-08: interrupted (server restart) and cancelled runs resume, skipping finished part files */
export const RESUMABLE: RunStatus[] = ['interrupted', 'cancelled']
export const DONE: RunStatus[] = ['completed', 'completed_with_errors']

/** Live progress of an active run from its job (patched by SSE `job.progress`, API-40) */
export function runProgress(r: RunSummary, jobs: Job[]): { done: number; total: number; eta: number | null } | null {
  if (!ACTIVE.includes(r.status)) return null
  const job = jobs.find((j) => j.job_id === r.job_id) ?? jobs.find((j) => j.kind === 'radiomics' && j.ref === r.run_id)
  if (!job) return { done: 0, total: r.counts.items, eta: null }
  return { done: job.done, total: job.total || r.counts.items, eta: job.eta_s ?? null }
}
