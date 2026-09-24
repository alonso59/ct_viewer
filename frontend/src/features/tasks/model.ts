// Task selection (TSK-03) from the tab's choice and the Explorer filter.
import type { CaseFilter, TaskRunStatus, TaskSelection } from '../../api'

export type SelectionMode = 'all' | 'explorer' | 'list'

export const ACTIVE_RUN: TaskRunStatus[] = ['queued', 'waiting_for_runner', 'running']
export const RESUMABLE_RUN: TaskRunStatus[] = ['failed', 'cancelled', 'interrupted']

export const RUN_TONE: Record<TaskRunStatus, string> = {
  queued: 'accent',
  waiting_for_runner: 'warn',
  running: 'accent',
  completed: 'ok',
  completed_with_errors: 'warn',
  failed: 'error',
  cancelled: 'muted',
  interrupted: 'warn',
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
