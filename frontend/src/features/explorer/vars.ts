// Variable-driven explorer helpers (VAR-10): which variables can filter, show as a column, or colour
import type { Variable, VariableValue } from '../../api'
import { fmtNum } from '../../lib'

const CATEGORICAL: Variable['type'][] = ['categorical', 'numeric-discrete']

export const isCategorical = (v: Variable) => CATEGORICAL.includes(v.type)
/** Visible variables with a filter control: categorical levels or a continuous range */
export const filterable = (vars: Variable[]) => vars.filter((v) => v.visible && (isCategorical(v) || v.type === 'continuous'))
/** Case-level visible variables: the ones a case row can show (VAR-02) */
export const columnable = (vars: Variable[]) => vars.filter((v) => v.visible && v.level === 'case' && v.type !== 'constant')
/** Colour needs a small, stable set of levels */
export const colorable = (vars: Variable[]) => columnable(vars).filter(isCategorical)

export const CAT_COLORS = 8

/** Stable colour per level: levels sorted by value, cycling through --cat-1..8 (DB-07 palette) */
export function levelColor(v: Variable, value: VariableValue): string | null {
  if (value === null || value === '') return null
  const levels = (v.profile.levels ?? []).map((l) => l.value).sort((a, b) => a.localeCompare(b, 'en', { numeric: true }))
  const i = levels.indexOf(String(value))
  return i < 0 ? null : `var(--cat-${(i % CAT_COLORS) + 1})`
}

export function formatValue(v: Variable | undefined, value: VariableValue): string {
  if (value === null || value === '') return '—'
  if (typeof value === 'number' || v?.type === 'continuous') {
    const n = Number(value)
    return Number.isFinite(n) ? fmtNum(n) : String(value)
  }
  return String(value)
}

/** `min..max` range filter value (API.md §Conventions); empty bounds are open */
export function rangeValue(min: string, max: string): string {
  return min === '' && max === '' ? '' : `${min}..${max}`
}
export function parseRange(spec: string | undefined): [string, string] {
  const m = /^(.*)\.\.(.*)$/.exec(spec ?? '')
  return m ? [m[1] ?? '', m[2] ?? ''] : ['', '']
}
