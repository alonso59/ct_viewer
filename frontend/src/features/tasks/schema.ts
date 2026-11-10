// The manifest's JSON Schema subset as form fields. Validation runs live here and authoritatively
// on the server.

export interface FieldSchema {
  type?: 'object' | 'boolean' | 'integer' | 'number' | 'string' | 'array'
  enum?: (string | number)[]
  default?: unknown
  minimum?: number
  maximum?: number
  pattern?: string
  items?: FieldSchema
  minItems?: number
  maxItems?: number
  uniqueItems?: boolean
  properties?: Record<string, FieldSchema>
  /** Object level: the property names that must be set */
  required?: string[]
  title?: string
  'x-help'?: string
  /** Display names for `enum` values, same order (e.g. a model title for its profile id) */
  'x-enumNames'?: string[]
  /** Per `enum` value: ready, warning or unavailable; an unavailable value cannot be picked */
  'x-enumStatus'?: ('ready' | 'warning' | 'unavailable')[]
  'x-advanced'?: boolean
  'x-group'?: string
}

interface FormField {
  name: string
  schema: FieldSchema
  required: boolean
}

export function fields(schema: unknown): FormField[] {
  const s = schema as FieldSchema | null
  const required = new Set(s?.required ?? [])
  return Object.entries(s?.properties ?? {}).map(([name, field]) => ({ name, schema: field, required: required.has(name) }))
}

/** Property-name suffixes that are units (`delay_s`, `spacing_mm`) */
const UNITS = new Set(['s', 'mm', 'mb', 'hu', 'pct'])

/** The manifest's title, else the property name in words ("patient_limit" → "Patient limit");
 *  `unit` is a unit suffix of the name, for `tasks.unit.*` */
export function fieldTitle(name: string, s: FieldSchema): { title: string; unit?: string } {
  const parts = name.split('_')
  const last = parts[parts.length - 1] ?? ''
  const unit = parts.length > 1 && UNITS.has(last) ? last : undefined
  if (s.title) return { title: s.title, unit }
  const words = (unit ? parts.slice(0, -1) : parts).join(' ')
  return { title: words.charAt(0).toUpperCase() + words.slice(1), unit }
}

export function defaults(schema: unknown): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of fields(schema)) if (f.schema.default !== undefined) out[f.name] = f.schema.default
  return out
}

/** Client-side checks mirroring the server (type, range, enum, pattern); returns field → message key */
export function check(schema: unknown, values: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const { name, schema: s } of fields(schema)) {
    const v = values[name]
    if (v === undefined || v === '') continue
    if (s.type === 'array') {
      if (!Array.isArray(v) || (s.items?.enum && v.some((item) => !s.items!.enum!.includes(item))) || (s.uniqueItems && new Set(v).size !== v.length)) out[name] = 'tasks.err.enum'
      else if (s.minItems !== undefined && v.length < s.minItems) out[name] = 'tasks.err.min'
      else if (s.maxItems !== undefined && v.length > s.maxItems) out[name] = 'tasks.err.max'
      continue
    }
    if ((s.type === 'integer' || s.type === 'number') && (typeof v !== 'number' || Number.isNaN(v))) out[name] = 'tasks.err.number'
    else if (s.type === 'integer' && typeof v === 'number' && !Number.isInteger(v)) out[name] = 'tasks.err.integer'
    else if (typeof v === 'number' && s.minimum !== undefined && v < s.minimum) out[name] = 'tasks.err.min'
    else if (typeof v === 'number' && s.maximum !== undefined && v > s.maximum) out[name] = 'tasks.err.max'
    else if (s.enum && !s.enum.includes(v as string | number)) out[name] = 'tasks.err.enum'
    else if (s.type === 'string' && s.pattern && typeof v === 'string' && !new RegExp(s.pattern).test(v)) out[name] = 'tasks.err.pattern'
  }
  return out
}

/** Only set values are sent (the server applies the defaults) */
export function toSettings(values: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(values).filter(([, v]) => v !== undefined && v !== ''))
}
