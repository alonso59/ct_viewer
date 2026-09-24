// The Explorer filter as a radiomics selection (RAD-05 "current Explorer filter"). API-33/34
// take either an item-id list or level lists (phase, side, `var`), so ranges and case-only
// criteria cannot be sent; they are reported as dropped.
import type { CaseFilter, Variable } from '../../api'

/** Criteria of the Explorer filter that have no API-33/34 equivalent */
export type DroppedCriterion = 'text' | 'status' | 'warning' | 'voi' | 'showExcluded' | 'phase' | 'vars'

export interface ExplorerSelection {
  /** DB-04 item list; when set, the other criteria are dropped (item_ids and filter are exclusive) */
  itemIds: string[] | null
  /** Scope shared by every listed item, if any */
  scope: 'complete' | 'voi' | null
  phase: string[]
  /** Level lists per variable (VAR-10) */
  vars: Record<string, string[]>
  /** Continuous variables filtered by a `min..max` range: bin them first (VAR-06) */
  ranges: string[]
  dropped: DroppedCriterion[]
}

const RANGE = /^.*\.\..*$/

export function explorerSelection(f: Readonly<CaseFilter>, variables: Variable[]): ExplorerSelection {
  const dropped: DroppedCriterion[] = []
  if (f.q?.trim()) dropped.push('text')
  if (f.status) dropped.push('status')
  if (f.warning) dropped.push('warning')
  if (f.voi) dropped.push('voi')
  if (f.showExcluded) dropped.push('showExcluded')
  const vars: Record<string, string[]> = {}
  const ranges: string[] = []
  for (const [name, value] of Object.entries(f.vars ?? {})) {
    if (!value) continue
    const type = variables.find((v) => v.name === name)?.type
    if (type === 'continuous' || (type === undefined && RANGE.test(value))) ranges.push(name)
    else vars[name] = [value]
  }
  const phase = f.phase ? [f.phase] : []
  if (f.itemIds) {
    if (phase.length) dropped.push('phase')
    if (Object.keys(vars).length) dropped.push('vars')
    const scopes = new Set(f.itemIds.map((id) => id.split('.').at(-2)))
    const only = scopes.size === 1 ? [...scopes][0] : undefined
    return {
      itemIds: [...f.itemIds],
      scope: only === 'complete' || only === 'voi' ? only : null,
      phase: [],
      vars: {},
      ranges,
      dropped,
    }
  }
  return { itemIds: null, scope: null, phase, vars, ranges, dropped }
}
