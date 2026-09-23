// Pure helpers for the derived-variable form (VAR-06)
import type { DerivedDef, Variable } from '../../api'

export const numericSources = (vars: Variable[]) => vars.filter((v) => v.type === 'continuous' || v.type === 'numeric-discrete')
export const categoricalSources = (vars: Variable[]) => vars.filter((v) => v.type === 'categorical' || v.type === 'numeric-discrete')

/** "10, 50" → [10, 50]; null when any entry is not a number */
export function parseNumbers(text: string): number[] | null {
  const parts = text.split(/[,;\s]+/).filter(Boolean)
  const nums = parts.map(Number)
  return nums.every(Number.isFinite) ? nums : null
}
export const parseLabels = (text: string) => text.split(',').map((s) => s.trim()).filter(Boolean)

/** Default bin labels: "<50", "≥50" for one threshold; "Q1..Qn" for quantiles; ranges otherwise */
export function defaultLabels(thresholds: number[] | null, quantiles: number | null): string[] {
  if (quantiles) return Array.from({ length: quantiles }, (_, i) => `Q${i + 1}`)
  if (!thresholds?.length) return []
  const t = [...thresholds].sort((a, b) => a - b)
  return [`<${t[0]}`, ...t.slice(1).map((x, i) => `${t[i]}–${x}`), `≥${t[t.length - 1]}`]
}

export interface DerivedDraft {
  name: string
  op: DerivedDef['op']
  source: string
  mode: 'thresholds' | 'quantiles'
  thresholds: string
  quantiles: string
  labels: string
  map: Record<string, string>
  sources: string[]
}

/** Draft → definition, or an i18n error key */
export function toDefinition(d: DerivedDraft): { def: DerivedDef } | { error: string } {
  const name = d.name.trim()
  if (!/^[a-z][a-z0-9_]*$/.test(name)) return { error: 'variables.err.name' }
  if (d.op === 'dominant') {
    if (d.sources.length < 2) return { error: 'variables.err.sources' }
    return { def: { name, op: 'dominant', sources: d.sources } }
  }
  if (!d.source) return { error: 'variables.err.source' }
  if (d.op === 'recode') {
    const map = Object.fromEntries(Object.entries(d.map).filter(([k, v]) => v.trim() && v.trim() !== k).map(([k, v]) => [k, v.trim()]))
    if (!Object.keys(map).length) return { error: 'variables.err.map' }
    return { def: { name, op: 'recode', source: d.source, map } }
  }
  const labels = parseLabels(d.labels)
  if (d.mode === 'quantiles') {
    const q = Number(d.quantiles)
    if (!Number.isInteger(q) || q < 2 || q > 10) return { error: 'variables.err.quantiles' }
    const l = labels.length ? labels : defaultLabels(null, q)
    if (l.length !== q) return { error: 'variables.err.labels' }
    return { def: { name, op: 'bin', source: d.source, quantiles: q, labels: l } }
  }
  const th = parseNumbers(d.thresholds)
  if (!th?.length) return { error: 'variables.err.thresholds' }
  const sorted = [...th].sort((a, b) => a - b)
  const l = labels.length ? labels : defaultLabels(sorted, null)
  if (l.length !== sorted.length + 1) return { error: 'variables.err.labels' }
  return { def: { name, op: 'bin', source: d.source, thresholds: sorted, labels: l } }
}
