// Analysis panel logic (ANALYSIS.md, DB-08/09): question validity, result ordering, number format.
// Pure functions; the backend (API-39) makes the final checks and choices.
import type { AnalysisQuestion, DashboardView, ResultRow, Variable } from '../../../api'

/** Variable types a question accepts (ANA-02, ANALYSIS §Tests) */
const ALLOWED: Record<Exclude<AnalysisQuestion, 'paired'>, readonly string[]> = {
  explore: [],
  compare: ['categorical'],
  association: ['continuous'],
  balance: ['categorical'],
}

/** Question types in panel order (`paired` is v3.1, ANA-10) */
export const QUESTIONS = ['explore', 'compare', 'association', 'balance'] as const
export type PanelQuestion = (typeof QUESTIONS)[number]

/** Variable types the panel lists at all (the rest cannot be analysed) */
const ANALYSABLE = new Set(['categorical', 'continuous', 'numeric-discrete'])

export const needsVariable = (q: PanelQuestion) => q !== 'explore'

/** A numeric-discrete type is still the inference: the user must confirm it first (VAR-03) */
export const needsConfirmation = (v: Pick<Variable, 'type'>) => v.type === 'numeric-discrete'

/** ANA-02: the questions valid for a variable (explore needs none) */
export function questionsFor(v: Pick<Variable, 'type'> | null | undefined): PanelQuestion[] {
  if (!v) return ['explore']
  return QUESTIONS.filter((q) => q !== 'explore' && ALLOWED[q].includes(v.type))
}

/** Variables offered as the analysis variable: visible and of an analysable type */
export function analysisVariables(vars: Variable[]): Variable[] {
  return vars
    .filter((v) => v.visible && ANALYSABLE.has(v.type))
    .sort((a, b) => Number(b.level === 'case') - Number(a.level === 'case') || a.name.localeCompare(b.name))
}

/** Confounder candidates: categorical, visible or tagged `confounder` (acquisition fields are hidden
 *  by default, VAR-04/05); tagged ones first. */
export function confounderVariables(vars: Variable[], exclude: string | null): Variable[] {
  return vars
    .filter((v) => v.type === 'categorical' && v.name !== exclude && (v.visible || v.tags.includes('confounder')))
    .sort((a, b) => Number(b.tags.includes('confounder')) - Number(a.tags.includes('confounder')) || a.name.localeCompare(b.name))
}

/** Default confounder for a balance check: the first tagged one */
export const suggestedConfounder = (vars: Variable[], exclude: string | null): string | null =>
  confounderVariables(vars, exclude).find((v) => v.tags.includes('confounder'))?.name ?? null

const nanLast = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? Infinity : v)

/** ANA-05: by q, then |effect| descending; untested rows (no q) last */
export function sortResults(rows: ResultRow[]): ResultRow[] {
  return [...rows].sort((a, b) => nanLast(a.q) - nanLast(b.q) || Math.abs(b.effect ?? 0) - Math.abs(a.effect ?? 0))
}

const fixed = new Intl.NumberFormat('en', { maximumFractionDigits: 3, minimumFractionDigits: 3 })
const sci = new Intl.NumberFormat('en', { notation: 'scientific', maximumFractionDigits: 2 })
const stat = new Intl.NumberFormat('en', { maximumSignificantDigits: 3 })

/** p/q values: three decimals, scientific below 0.001 */
export function fmtP(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  if (v === 0) return '0'
  return v < 0.001 ? sci.format(v) : fixed.format(v)
}

/** Statistics and effect sizes: three significant digits */
export function fmtStat(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return Math.abs(v) >= 1e5 || (v !== 0 && Math.abs(v) < 1e-3) ? sci.format(v) : stat.format(v)
}

/** DB-09: the view that shows one result row */
export function viewForResult(question: AnalysisQuestion): DashboardView | null {
  if (question === 'compare') return 'group-comparison'
  if (question === 'association') return 'association'
  if (question === 'balance') return 'balance'
  return null
}

/** q < this counts as significant in the summary line */
export const Q_SIGNIFICANT = 0.05
