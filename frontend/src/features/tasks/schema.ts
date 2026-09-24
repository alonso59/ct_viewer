// TSK-02: the manifest's JSON Schema subset (TASKS.md §Manifest) as form fields. Validation runs
// live here and authoritatively on the server (API-43).

export interface FieldSchema {
  type?: 'object' | 'boolean' | 'integer' | 'number' | 'string' | 'array'
  enum?: (string | number)[]
  default?: unknown
  minimum?: number
  maximum?: number
  pattern?: string
  items?: FieldSchema
  properties?: Record<string, FieldSchema>
  'x-help'?: string
  'x-advanced'?: boolean
  'x-group'?: string
}

export interface FormField {
  name: string
  schema: FieldSchema
}

export function fields(schema: unknown): FormField[] {
  const props = (schema as FieldSchema | null)?.properties ?? {}
  return Object.entries(props).map(([name, s]) => ({ name, schema: s }))
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
