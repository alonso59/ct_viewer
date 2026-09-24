// Mock radiomics engine for VITE_API_MODE=mock (API-30..37). The schema is the live PyRadiomics
// fixture and validation reuses the settings form's rules, so the settings tab behaves like the
// server. Both load lazily: they stay out of the initial bundle (NFR-07).
import i18n from '../../i18n'
import type { ItemRecord, Profile, RadiomicsSettings, RunDetail, RunSummary, Selection, SettingsSchema, ValidateResult, ValidationIssue } from '../types'

export interface MockEngine {
  schema: SettingsSchema
  /** Full normalized snapshot (engine defaults filled in), as the server stores it */
  normalize(settings: RadiomicsSettings): RadiomicsSettings
  validate(settings: RadiomicsSettings, labels: number[] | null, nItems: number | null): ValidateResult
}

let engine: Promise<MockEngine> | null = null

export function loadEngine(): Promise<MockEngine> {
  engine ??= Promise.all([
    import('../../features/radiomics/model/fixtures/schema.json'),
    import('../../features/radiomics/model/settings'),
    import('../../features/radiomics/model/validate'),
  ]).then(([json, settings, rules]) => {
    const schema = json.default as unknown as SettingsSchema
    const normalize = (s: RadiomicsSettings) => settings.toWire(schema, settings.fromWire(schema, s))
    return {
      schema,
      normalize,
      validate(s, labels, nItems) {
        const found = rules.validateForm(schema, settings.fromWire(schema, s), { labels: labels ?? [1], nItems })
        const issues: ValidationIssue[] = found.map((x) => ({
          loc: x.loc,
          rule: x.rule,
          severity: x.severity,
          msg: x.msg ?? (x.key ? i18n.t(`rad.rule.${x.key}`, x.params ?? {}) : x.rule),
        }))
        const ok = !issues.some((x) => x.severity === 'error')
        const norm = normalize(s)
        return { ok, issues, settings: ok ? norm : null, profile_hash: ok ? profileHash(norm) : null }
      },
    }
  })
  return engine
}

/** Stable JSON (sorted keys) so equal settings hash equally (RAD-03) */
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`
  if (v && typeof v === 'object')
    return `{${Object.keys(v)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical((v as Record<string, unknown>)[k])}`)
      .join(',')}}`
  return JSON.stringify(v ?? null)
}

/** Deterministic 64-hex digest (FNV-1a lanes; a mock stand-in for the server's sha256) */
export function profileHash(settings: RadiomicsSettings): string {
  const text = canonical(settings)
  let out = ''
  for (let lane = 0; lane < 8; lane++) {
    let h = 0x811c9dc5 ^ lane
    for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193)
    out += (h >>> 0).toString(16).padStart(8, '0')
  }
  return `sha256:${out}`
}

export function engineOf(schema: SettingsSchema): Profile['engine'] {
  return { ...schema.engine, major: schema.engine.version.split('.')[0] ?? '' }
}

/** Items a selection resolves to (RAD-05): active, with a mask, matching scope, filter or id list */
export function selectItems(items: ItemRecord[], sel: Selection, valueOf: (i: ItemRecord, name: string) => unknown): ItemRecord[] {
  const ids = sel.item_ids ? new Set(sel.item_ids) : null
  const f = sel.filter
  return items.filter((i) => {
    if (i.status !== 'active' || !i.mask) return false
    if (ids) return ids.has(i.item_id)
    if (i.scope !== (sel.scope ?? 'complete')) return false
    if (f?.phase?.length && !f.phase.includes(i.phase.canonical)) return false
    if (f?.side?.length && !f.side.includes(i.side)) return false
    for (const [name, levels] of Object.entries(f?.var ?? {})) {
      const v = valueOf(i, name)
      if (levels.length && !levels.includes(v == null ? '' : String(v))) return false
    }
    return true
  })
}

export function toSummary(r: RunDetail): RunSummary {
  const { run_id, name, status, created_at, started_at, finished_at, reviewer, profile_hash, selection, counts, job_id } = r
  return { run_id, name, status, created_at, started_at, finished_at, reviewer, profile_hash, selection, counts, job_id }
}
