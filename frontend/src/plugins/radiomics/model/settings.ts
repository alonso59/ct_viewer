// Schema-driven form model (RAD-01/02): nothing about the engine's options is hard-coded here.
// The form opens on `schema.defaults` (engine defaults) and round-trips to `RadiomicsSettings`.
import type { FeatureClassSpec, FilterSpec, FormState, OptionSpec, SettingsSchema, Value, WireSettings } from './types'

function asValue(v: unknown): Value {
  if (v === null || v === undefined) return null
  if (typeof v === 'boolean' || typeof v === 'number' || typeof v === 'string') return v
  if (Array.isArray(v)) return v.filter((x): x is number => typeof x === 'number')
  return null
}

const optionDefault = (o: OptionSpec): Value => asValue(o.default)

/** Features a class turns on when its checkbox is ticked: the engine's default-enabled set */
export const defaultFeatures = (c: FeatureClassSpec): string[] => c.features.filter((f) => f.default_enabled).map((f) => f.name)

/** Build the form from a wire settings object; missing parts fall back to the schema defaults. */
export function fromWire(schema: SettingsSchema, wire: WireSettings = schema.defaults): FormState {
  const types = wire.image_types ?? schema.defaults.image_types ?? {}
  const feats = wire.features ?? schema.defaults.features ?? {}
  const settings = { ...(schema.defaults.settings ?? {}), ...(wire.settings ?? {}) }
  const filters: FormState['filters'] = {}
  for (const f of schema.filters) {
    const given = types[f.name]
    const params: Record<string, Value> = {}
    for (const p of f.params ?? []) params[p.name] = given && p.name in given ? asValue(given[p.name]) : optionDefault(p)
    filters[f.name] = { enabled: given !== undefined, params }
  }
  const features: FormState['features'] = {}
  for (const c of schema.feature_classes) {
    if (!(c.name in feats)) features[c.name] = []
    else features[c.name] = feats[c.name] ?? defaultFeatures(c)
  }
  const options: FormState['options'] = {}
  for (const o of schema.options) options[o.name] = o.name in settings ? asValue(settings[o.name]) : optionDefault(o)
  return { filters, features, options }
}

export const defaultForm = (schema: SettingsSchema): FormState => fromWire(schema, schema.defaults)

/** Full normalized snapshot sent to API-31/33/34 and stored in profiles */
export function toWire(schema: SettingsSchema, form: FormState): WireSettings {
  const image_types: Record<string, Record<string, unknown>> = {}
  for (const f of schema.filters) {
    const s = form.filters[f.name]
    if (s?.enabled) image_types[f.name] = { ...s.params }
  }
  const features: Record<string, string[]> = {}
  for (const c of schema.feature_classes) {
    const picked = form.features[c.name] ?? []
    // Keep the engine's feature order so equal selections hash equally (RAD-03)
    if (picked.length) features[c.name] = c.features.map((x) => x.name).filter((n) => picked.includes(n))
  }
  const settings: Record<string, unknown> = {}
  for (const o of schema.options) settings[o.name] = form.options[o.name] ?? null
  return { image_types, features, settings }
}

/** Options of the schema grouped for the navigation, in schema group order; empty groups dropped */
export function optionsByGroup(schema: SettingsSchema): Map<string, OptionSpec[]> {
  const out = new Map<string, OptionSpec[]>()
  for (const g of schema.groups) out.set(g.id, [])
  for (const o of schema.options) {
    const list = out.get(o.group)
    if (list) list.push(o)
    else out.set(o.group, [o])
  }
  return out
}

/** Filters that can be switched on (the engine reports missing optional packages as unavailable) */
export const isSelectable = (f: FilterSpec) => f.available

/** Number of features that will be extracted per image type */
export const featureCount = (form: FormState) => Object.values(form.features).reduce((n, l) => n + l.length, 0)

export function setOption(form: FormState, name: string, v: Value): FormState {
  return { ...form, options: { ...form.options, [name]: v } }
}

export function setFilter(form: FormState, name: string, patch: { enabled?: boolean; params?: Record<string, Value> }): FormState {
  const cur = form.filters[name] ?? { enabled: false, params: {} }
  return {
    ...form,
    filters: { ...form.filters, [name]: { enabled: patch.enabled ?? cur.enabled, params: { ...cur.params, ...(patch.params ?? {}) } } },
  }
}

export function setFeatures(form: FormState, cls: string, list: string[]): FormState {
  return { ...form, features: { ...form.features, [cls]: list } }
}

/** Parse a comma/space separated list input; `null` for an empty input */
export function parseList(text: string, int: boolean): number[] | null {
  const parts = text.split(/[,;\s]+/).filter(Boolean)
  if (!parts.length) return null
  return parts.map((x) => (int ? Number(x) : parseFloat(x)))
}
