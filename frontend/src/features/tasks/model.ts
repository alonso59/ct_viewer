// Task selection (TSK-03) from the tab's choice and the Explorer filter.
import type { CaseFilter, TaskRunStatus, TaskRunSummary, TaskSelection } from '../../api'

export type SelectionMode = 'all' | 'explorer' | 'list'

export const ACTIVE_RUN: TaskRunStatus[] = ['queued', 'waiting_for_runner', 'waiting_for_resources', 'running']
/** TSK-15: a pause/cancel was requested; the supervisor has not confirmed cleanup yet */
export const STOPPING_RUN: TaskRunStatus[] = ['pausing', 'cancelling', 'reconciling', 'cleanup_pending']
export const RESUMABLE_RUN: TaskRunStatus[] = ['failed', 'cancelled', 'interrupted', 'paused', 'completed_with_errors']

type Run = Pick<TaskRunSummary, 'status' | 'supervised' | 'archived' | 'control' | 'task'> & Partial<Pick<TaskRunSummary, 'counts'>>
export type RunAction = 'pause' | 'cancel' | 'resume' | 'archive' | 'retry_failed'

/** The lifecycle actions a run offers (J3..J6); none on view-only links (U1) */
export function runActions(run: Run, readOnly: boolean): RunAction[] {
  if (readOnly || run.archived) return []
  const out: RunAction[] = []
  const supervised = !!run.supervised
  const cancelPending = run.control?.action === 'cancel' && !run.control.acknowledged_at
  if (supervised && ACTIVE_RUN.includes(run.status)) out.push('pause')
  if (ACTIVE_RUN.includes(run.status) || (supervised && STOPPING_RUN.includes(run.status) && !cancelPending)) out.push('cancel')
  const resumable = run.task.id !== 'radiomics.pyradiomics' && RESUMABLE_RUN.includes(run.status)
  if (resumable && (supervised || run.task.id === 'dicom.convert' || !['paused', 'completed_with_errors'].includes(run.status))) out.push('resume')
  if (resumable && run.task.id === 'dicom.convert' && (run.counts?.failed ?? 0) > 0) out.push('retry_failed')
  if (supervised && !ACTIVE_RUN.includes(run.status) && !STOPPING_RUN.includes(run.status)) out.push('archive')
  return out
}


/** Explorer filter → selection: item list wins; phase and categorical variables map; ranges don't */
export function fromExplorer(f: Readonly<CaseFilter>): TaskSelection {
  if (f.itemIds?.length) return { item_ids: [...f.itemIds] }
  const variables = Object.fromEntries(Object.entries(f.vars ?? {}).filter(([, v]) => v && !v.includes('..')).map(([k, v]) => [k, [v]]))
  const filter = { phase: f.phase ? [f.phase] : null, var: Object.keys(variables).length ? variables : null }
  return filter.phase || filter.var ? { filter } : {}
}

export function selectionFor(mode: SelectionMode, explorer: Readonly<CaseFilter>, list: string, extra: Partial<TaskSelection>): TaskSelection {
  const base = mode === 'explorer' ? fromExplorer(explorer) : mode === 'list' ? { item_ids: parseIds(list) } : {}
  return { ...base, ...extra }
}

export const parseIds = (text: string) => [...new Set(text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean))]
