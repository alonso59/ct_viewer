// Run selection (RAD-05): items (all active / filter on any variable / explicit list), scope, labels.
import type { Selection, SelectionFilter } from './types'

export type ItemsMode = 'all' | 'filter' | 'list'
export type Side = NonNullable<SelectionFilter['side']>[number]
export const SIDES: Side[] = ['L', 'R', '-']

export interface SelectionForm {
  mode: ItemsMode
  scope: 'complete' | 'voi'
  labels: number[]
  /** Filter mode: phases, sides and levels per variable; an empty list means "any" */
  phase: string[]
  side: Side[]
  vars: Record<string, string[]>
  /** List mode: item ids separated by newlines, commas or spaces */
  list: string
  /** RAD-05: segmentation set whose masks are read; null = the project's default_seg */
  seg?: string | null
}

export const emptySelection = (labels: number[] = []): SelectionForm => ({
  mode: 'all',
  scope: 'complete',
  labels,
  phase: [],
  side: [],
  vars: {},
  list: '',
})

export function parseItemIds(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean))]
}

export function toFilter(s: SelectionForm): SelectionFilter | null {
  const vars = Object.fromEntries(Object.entries(s.vars).filter(([, levels]) => levels.length > 0))
  const f: SelectionFilter = {}
  if (s.phase.length) f.phase = [...s.phase]
  if (s.side.length) f.side = [...s.side]
  if (Object.keys(vars).length) f.var = vars
  return Object.keys(f).length ? f : null
}

/** API-33/34 `selection` body */
export function toSelection(s: SelectionForm): Selection {
  const out: Selection = { scope: s.scope, labels: [...s.labels].sort((a, b) => a - b) }
  if (s.mode === 'filter') {
    const f = toFilter(s)
    if (f) out.filter = f
  }
  if (s.mode === 'list') out.item_ids = parseItemIds(s.list)
  if (s.seg) out.seg_id = s.seg
  return out
}

/** Items known to be empty before asking the server (explicit list with no ids) */
export const knownEmpty = (s: SelectionForm) => s.mode === 'list' && parseItemIds(s.list).length === 0

/** Number of active filter criteria (for the summary) */
export function criteriaCount(s: SelectionForm): number {
  const f = toFilter(s)
  if (!f) return 0
  return (f.phase ? 1 : 0) + (f.side ? 1 : 0) + Object.keys(f.var ?? {}).length
}
