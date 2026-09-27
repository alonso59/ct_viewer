// Live validation (RAD-04, RADIOMICS.md §Validation rules). The server (API-43) is authoritative;
// this mirrors its rules and `loc` paths so the form can flag fields before the round trip.
import { featureCount } from './settings'
import type { FormState, Issue, OptionSpec, ServerIssue, SettingsSchema, Value } from './types'

export interface ValidationContext {
  labels: number[]
  /** Items in the selection when known (after an estimate); `null` = unknown, not checked */
  nItems: number | null
}

const err = (loc: Issue['loc'], rule: string, key: string, params?: Issue['params']): Issue => ({ loc, rule, severity: 'error', key, params })

function checkNumber(o: OptionSpec, v: number, loc: Issue['loc']): Issue | null {
  if (!Number.isFinite(v)) return err(loc, 'type', 'number')
  if ((o.type === 'int' || o.type === 'int_list') && !Number.isInteger(v)) return err(loc, 'type', 'integer')
  const c = o.constraints
  if (!c) return null
  const min = c.min ?? null
  const max = c.max ?? null
  const low = min !== null && (c.exclusive_min ? v <= min : v < min)
  const high = max !== null && (c.exclusive_max ? v >= max : v > max)
  if (!low && !high) return null
  if (o.name === 'resampledPixelSpacing') return err(loc, 'constraint', 'spacing')
  if (min !== null && max !== null) return err(loc, 'constraint', 'range', { min, max })
  if (min !== null) return err(loc, 'constraint', c.exclusive_min ? 'gt' : 'ge', { min })
  return err(loc, 'constraint', c.exclusive_max ? 'lt' : 'le', { max: max ?? 0 })
}

/** Type and constraint checks for one option value (API-30 `type`, `nullable`, `constraints`) */
export function checkOption(o: OptionSpec, v: Value, loc: Issue['loc']): Issue[] {
  if (v === null) return o.nullable ? [] : [err(loc, 'type', 'required')]
  switch (o.type) {
    case 'bool':
      return typeof v === 'boolean' ? [] : [err(loc, 'type', 'required')]
    case 'int':
    case 'float': {
      if (typeof v !== 'number') return [err(loc, 'type', 'number')]
      const i = checkNumber(o, v, loc)
      return i ? [i] : []
    }
    case 'enum': {
      const choices = o.constraints?.enum ?? []
      return typeof v === 'string' && choices.includes(v) ? [] : [err(loc, 'constraint', 'choice')]
    }
    case 'str':
      return typeof v === 'string' ? [] : [err(loc, 'type', 'required')]
    case 'float_list':
    case 'int_list': {
      if (!Array.isArray(v)) return [err(loc, 'type', 'list')]
      const c = o.constraints
      const lo = c?.min_items ?? null
      const hi = c?.max_items ?? null
      if ((lo !== null && v.length < lo) || (hi !== null && v.length > hi)) {
        if (o.name === 'resampledPixelSpacing') return [err(loc, 'constraint', 'spacing')]
        return [err(loc, 'constraint', lo === hi ? 'count' : 'countRange', { min: lo ?? 0, max: hi ?? '∞' })]
      }
      const out: Issue[] = []
      v.forEach((x, i) => {
        const e = checkNumber(o, x, [...loc, i])
        if (e) out.push(e)
      })
      return out
    }
  }
}

export function validateForm(schema: SettingsSchema, form: FormState, ctx: ValidationContext): Issue[] {
  const issues: Issue[] = []
  const opt = (n: string): Value => form.options[n] ?? null

  // Per-option types and constraints
  for (const o of schema.options) issues.push(...checkOption(o, opt(o.name), ['settings', o.name]))
  for (const f of schema.filters) {
    const s = form.filters[f.name]
    if (!s?.enabled) continue
    if (!f.available) issues.push(err(['image_types', f.name], 'unavailable', 'unavailable', { reason: f.unavailable_reason ?? '' }))
    for (const p of f.params ?? []) issues.push(...checkOption(p, s.params[p.name] ?? null, ['image_types', f.name, p.name]))
  }

  // Bin width xor bin count, one required
  const hasW = opt('binWidth') !== null
  const hasC = opt('binCount') !== null
  if (hasW === hasC && 'binWidth' in form.options && 'binCount' in form.options) {
    issues.push(err(['settings', 'binWidth'], 'bin_xor', 'binXor'), err(['settings', 'binCount'], 'bin_xor', 'binXor'))
  }

  // LoG needs at least one sigma > 0
  const log = form.filters.LoG
  if (log?.enabled) {
    const sigma = log.params.sigma
    if (!Array.isArray(sigma) || !sigma.some((x) => x > 0)) issues.push(err(['image_types', 'LoG', 'sigma'], 'log_sigma', 'logSigma'))
  }

  // 2D-only classes and filters need force2D
  if (opt('force2D') !== true) {
    for (const c of schema.feature_classes)
      if (c.requires_2d && (form.features[c.name]?.length ?? 0) > 0) issues.push(err(['features', c.name], 'force_2d', 'force2d'))
    for (const f of schema.filters)
      if (f.requires_2d && form.filters[f.name]?.enabled) issues.push(err(['image_types', f.name], 'force_2d', 'force2d'))
  }

  // Re-segmentation range
  const range = opt('resegmentRange')
  const mode = opt('resegmentMode')
  if (Array.isArray(range)) {
    if (mode === 'sigma') {
      if (range.length !== 1 || !((range[0] ?? 0) > 0)) issues.push(err(['settings', 'resegmentRange'], 'reseg_sigma', 'resegSigma'))
    } else if (range.length === 2 && (range[0] ?? 0) >= (range[1] ?? 0)) {
      issues.push(err(['settings', 'resegmentRange'], 'reseg_order', 'resegOrder'))
    }
  }

  // Nothing to extract
  if (featureCount(form) === 0) issues.push(err(['features'], 'nothing', 'nothing'))
  if (!Object.values(form.filters).some((f) => f.enabled)) issues.push(err(['image_types'], 'nothing', 'nothing'))
  if (ctx.labels.length === 0) issues.push(err(['labels'], 'nothing', 'nothing'))
  if (ctx.nItems === 0) issues.push(err(['n_items'], 'nothing', 'nothing'))

  // Warning: an absolute (HU) range is applied after normalization
  if (opt('normalize') === true && Array.isArray(range) && mode === 'absolute')
    issues.push({ loc: ['settings', 'normalize'], rule: 'normalize_hu', severity: 'warning', key: 'normalizeHu' })

  return dedupe(issues)
}

function dedupe(issues: Issue[]): Issue[] {
  const seen = new Set<string>()
  return issues.filter((i) => {
    const k = `${i.loc.join('.')}|${i.rule}|${i.key ?? i.msg ?? ''}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

export const fromServer = (i: ServerIssue): Issue => ({ loc: i.loc, rule: i.rule, severity: i.severity, msg: i.msg })

/** Field key for an issue: `settings.binWidth`, `image_types.LoG.sigma`, `features.shape2D`; list indexes dropped */
export const fieldOf = (loc: Issue['loc']): string => loc.filter((p) => typeof p === 'string').join('.')

export const hasErrors = (issues: Issue[]) => issues.some((i) => i.severity === 'error')

/** Navigation pseudo-group for the selection section */
export const SELECTION = 'selection'

/** Navigation group of an issue, so the nav can badge it and a click can jump there */
export function groupOf(schema: SettingsSchema, i: Issue): string {
  const [root, name] = i.loc
  if (root === 'image_types') return 'filters'
  if (root === 'features') return 'feature_classes'
  if (root === 'labels' || root === 'n_items') return SELECTION
  return schema.options.find((o) => o.name === name)?.group ?? 'other'
}
