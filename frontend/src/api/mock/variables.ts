// Mock of the variables backend (VARIABLES.md): profiling + type/level inference (VAR-01..04),
// default tags (VAR-05), derived variables (VAR-06), external tables (VAR-07), exclusions (VAR-09).
// Pure functions so the rules are unit-tested; the real implementation is backend `variables/`.
import type { DerivedDef, Variable, VariableGroup, VariableTag, VariableType, VariableValue } from '../types'

/** One row per item: case id, patient id and raw field values (core fields removed) */
export interface Row {
  case_id: string
  patient_id: string | null
  values: Record<string, unknown>
}

/** Fields of the known converter schema → Acquisition group (VAR-04); everything else is Study */
const ACQUISITION = new Set([
  'manufacturer', 'manufacturer_model', 'convolution_kernel', 'kvp', 'slice_thickness', 'spacing_z',
  'contrast_agent', 'modality', 'upstream_status', 'status', 'scan_date', 'phase_guess_evidence',
])
const CONFOUNDERS = new Set([
  'manufacturer', 'manufacturer_model', 'convolution_kernel', 'kvp', 'slice_thickness', 'spacing_z',
  'contrast_agent', 'modality',
])
/** VAR-09: never variables */
const NEVER = /(^|_)(uid|path|file|accession_?number)$|^accessionnumber$/i
const SENSITIVE = new Set(['patient_id'])
const REVIEW_BELOW = 0.8

export const isMissing = (v: unknown) => v === null || v === undefined || (typeof v === 'string' && v.trim() === '')
const isNum = (v: unknown) => typeof v === 'number' || (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)))
const DATE = /^(\d{4}-\d{2}-\d{2}([T ][\d:.]+Z?)?|\d{8})$/

/** VAR-03 §Type inference rules → type + confidence */
export function inferType(values: unknown[]): { type: VariableType; confidence: number } {
  const present = values.filter((v) => !isMissing(v))
  const n = present.length
  if (n === 0) return { type: 'constant', confidence: 1 }
  const distinct = new Set(present.map((v) => String(v))).size
  if (distinct === 1) return { type: 'constant', confidence: 1 }
  const numShare = present.filter(isNum).length / n
  const dateShare = present.filter((v) => typeof v === 'string' && DATE.test(v.trim())).length / n
  if (dateShare >= 0.95) return { type: 'date', confidence: dateShare }
  if (numShare >= 0.95) {
    if (distinct >= 10) return { type: 'continuous', confidence: numShare }
    return { type: 'numeric-discrete', confidence: 0.5 }
  }
  if (distinct <= 20 || distinct <= 0.05 * n) return { type: 'categorical', confidence: distinct <= 20 ? 0.95 : 0.85 }
  if (distinct >= 0.95 * n) return { type: 'identifier', confidence: distinct / n }
  return { type: 'text', confidence: 0.6 }
}

/** VAR-02: case-level when constant within every case */
export function inferLevel(rows: Row[], name: string): 'case' | 'scan' {
  const seen = new Map<string, string>()
  for (const r of rows) {
    const v = r.values[name]
    const s = isMissing(v) ? '' : String(v)
    const prev = seen.get(r.case_id)
    if (prev !== undefined && prev !== s) return 'scan'
    seen.set(r.case_id, s)
  }
  return 'case'
}

export interface Override {
  type?: VariableType
  visible?: boolean
  tags?: VariableTag[]
}

/** Profile one field over all rows (VAR-01). Missing % and levels count cases for case-level fields. */
export function profileField(rows: Row[], name: string, source: Variable['source'], ov: Override = {}): Variable {
  const level = inferLevel(rows, name)
  const unit = level === 'case' ? [...new Map(rows.map((r) => [r.case_id, r.values[name]])).values()] : rows.map((r) => r.values[name])
  const { type: inferred, confidence } = inferType(unit)
  const type = ov.type ?? inferred
  const present = unit.filter((v) => !isMissing(v))
  const group: VariableGroup = source === 'metadata' && ACQUISITION.has(name) ? 'acquisition' : 'study'
  const counts = new Map<string, number>()
  for (const v of present) counts.set(String(v), (counts.get(String(v)) ?? 0) + 1)
  const nums = type === 'continuous' ? present.filter(isNum).map(Number) : []
  const defaultTags: VariableTag[] = [...(CONFOUNDERS.has(name) ? (['confounder'] as const) : []), ...(SENSITIVE.has(name) ? (['sensitive'] as const) : [])]
  return {
    name,
    source,
    type,
    inferred_type: inferred,
    level,
    group,
    tags: ov.tags ?? defaultTags,
    visible: ov.visible ?? (group === 'study' && inferred !== 'constant' && inferred !== 'identifier' && !SENSITIVE.has(name)),
    confidence: +confidence.toFixed(2),
    review: ov.type === undefined && (inferred === 'numeric-discrete' || confidence < REVIEW_BELOW),
    overridden: ov.type !== undefined || ov.visible !== undefined || ov.tags !== undefined,
    profile: {
      missing_pct: unit.length ? +((100 * (unit.length - present.length)) / unit.length).toFixed(1) : 0,
      n_distinct: counts.size,
      examples: [...counts.keys()].slice(0, 5),
      ...(nums.length ? { min: Math.min(...nums), max: Math.max(...nums) } : {}),
      ...(type === 'categorical' || type === 'numeric-discrete'
        ? { levels: [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([value, count]) => ({ value, count })) }
        : {}),
    },
  }
}

/** Every non-core field that may be a variable (VAR-08/09) */
export function candidateFields(rows: Row[]): string[] {
  const names = new Set<string>()
  for (const r of rows) for (const k of Object.keys(r.values)) if (!NEVER.test(k)) names.add(k)
  return [...names].sort()
}

// ---- VAR-06 derived ----------------------------------------------------------------------------
function quantileCuts(values: number[], q: number): number[] {
  const s = [...values].sort((a, b) => a - b)
  return Array.from({ length: q - 1 }, (_, i) => s[Math.floor(((i + 1) * s.length) / q)] ?? 0)
}

/** Value of a derived variable for one row */
export function deriveValue(def: DerivedDef, values: Record<string, unknown>, all: Row[]): VariableValue {
  if (def.op === 'recode') {
    const v = values[def.source]
    return isMissing(v) ? null : (def.map[String(v)] ?? String(v))
  }
  if (def.op === 'dominant') {
    let best: string | null = null
    let max = -Infinity
    for (const s of def.sources) {
      const v = values[s]
      if (isNum(v) && Number(v) > max) {
        max = Number(v)
        best = s
      }
    }
    return best
  }
  const v = values[def.source]
  if (!isNum(v)) return null
  const cuts = def.thresholds?.length
    ? def.thresholds
    : quantileCuts(all.map((r) => r.values[def.source]).filter(isNum).map(Number), def.quantiles ?? 2)
  const i = cuts.filter((c) => Number(v) >= c).length
  return def.labels[i] ?? `bin_${i + 1}`
}

export function validateDerived(def: DerivedDef, known: Set<string>): string | null {
  if (!/^[a-z][a-z0-9_]*$/.test(def.name)) return 'Name must start with a letter and use a–z, 0–9, _'
  if (known.has(def.name)) return `A variable named "${def.name}" already exists`
  const sources = def.op === 'dominant' ? def.sources : [def.source]
  if (def.op === 'dominant' && sources.length < 2) return 'Pick at least two numeric variables'
  for (const s of sources) if (!known.has(s)) return `Unknown variable "${s}"`
  if (def.op === 'bin') {
    const bins = def.thresholds?.length ? def.thresholds.length + 1 : (def.quantiles ?? 0)
    if (bins < 2) return 'Give thresholds or at least 2 quantiles'
    if (def.labels.length !== bins) return `Give ${bins} labels`
  }
  return null
}

// ---- VAR-07 external table ---------------------------------------------------------------------
export function parseTable(text: string): { header: string[]; rows: string[][] } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== '')
  const sep = (lines[0] ?? '').includes('\t') ? '\t' : ','
  const split = (l: string) => l.split(sep).map((c) => c.trim().replace(/^"(.*)"$/, '$1'))
  return { header: split(lines[0] ?? ''), rows: lines.slice(1).map(split) }
}
