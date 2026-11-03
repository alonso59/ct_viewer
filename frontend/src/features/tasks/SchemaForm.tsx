import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { NumberInput } from '../../lib'
import { fieldTitle, fields, type FieldSchema } from './schema'

/** Help, default and error are linked to the field; an error shows once the field is left (or chosen),
 *  never while typing */
function Field({ name, schema, required, value, error, onChange, onLeave }: {
  name: string
  schema: FieldSchema
  required: boolean
  value: unknown
  error?: string
  onChange: (v: unknown) => void
  onLeave: () => void
}) {
  const { t } = useTranslation()
  const id = `task-field-${name}`
  const label = (s: FieldSchema, i: number, o: unknown) => s['x-enumNames']?.[i] ?? String(o)
  const { title, unit } = fieldTitle(name, schema)
  const fallback = schema.default === undefined || schema.type === 'boolean' ? null : schema.enum ? label(schema, schema.enum.indexOf(schema.default as string | number), schema.default) : String(schema.default)
  const help = [schema['x-help'], fallback === null ? null : t('tasks.defaultValue', { value: fallback })].filter(Boolean).join(' · ')
  const a11y = {
    'aria-describedby': [help ? `${id}-help` : '', error ? `${id}-error` : ''].filter(Boolean).join(' ') || undefined,
    'aria-invalid': error ? true : undefined,
    'aria-required': required || undefined,
    onBlur: onLeave,
  }
  // a choice is made at once: its error may show at once too
  const chose = (v: unknown) => {
    onChange(v)
    onLeave()
  }
  let input
  if (schema.type === 'array' && schema.items?.enum) {
    const items = schema.items
    const picked = Array.isArray(value) ? value.map(String) : []
    const full = schema.maxItems !== undefined && picked.length >= schema.maxItems
    const toggle = (o: string) => chose(picked.includes(o) ? picked.filter((p) => p !== o) : [...picked, o])
    input = (
      <div className="task-chips">
        {/* a group takes no aria-required; the label says it */}
        <span id={id} role="group" aria-labelledby={`${id}-label`} className="seg" {...a11y} aria-required={undefined}>
          {items.enum?.map((o, i) => {
            const on = picked.includes(String(o))
            return (
              <button key={String(o)} type="button" aria-pressed={on} disabled={!on && full} onClick={() => toggle(String(o))}>
                {label(items, i, o)}
              </button>
            )
          })}
        </span>
        {!picked.length ? <span className="muted task-help">{t('tasks.noneSelected')}</span> : null}
      </div>
    )
  } else if (schema.type === 'boolean') {
    input = <input id={id} type="checkbox" checked={Boolean(value ?? schema.default)} {...a11y} onChange={(e) => chose(e.target.checked)} />
  } else if (schema.enum) {
    input = (
      <select id={id} className="select" value={String(value ?? schema.default ?? '')} {...a11y} onChange={(e) => chose(e.target.value || undefined)}>
        {schema.default === undefined ? <option value="">{t('tasks.fromProject')}</option> : null}
        {schema.enum.map((o, i) => (
          <option key={String(o)} value={String(o)}>{label(schema, i, o)}</option>
        ))}
      </select>
    )
  } else if (schema.type === 'integer' || schema.type === 'number') {
    input = (
      <NumberInput
        id={id}
        className="input num"
        step={schema.type === 'integer' ? 1 : 0.1}
        min={schema.minimum}
        max={schema.maximum}
        placeholder={schema.default === undefined ? '' : String(schema.default)}
        value={typeof value === 'number' ? value : null}
        {...a11y}
        onChange={(n, raw) => onChange(raw.trim() === '' ? undefined : (n ?? Number.NaN))}
      />
    )
  } else {
    input = (
      <input id={id} className="input mono" placeholder={schema.default === undefined ? '' : String(schema.default)} value={typeof value === 'string' ? value : ''} {...a11y} onChange={(e) => onChange(e.target.value || undefined)} />
    )
  }
  return (
    <div className="task-field">
      <label id={`${id}-label`} className="field-label" htmlFor={id} title={name}>
        {title}
        {/* screen readers hear aria-required on the input instead */}
        {required ? <span className="task-required" aria-hidden="true">{t('tasks.required')}</span> : null}
      </label>
      {unit ? (
        <div className="task-input">
          {input}
          <span className="muted">{t(`tasks.unit.${unit}`)}</span>
        </div>
      ) : (
        input
      )}
      {help ? <span id={`${id}-help`} className="muted task-help">{help}</span> : null}
      {error ? <span id={`${id}-error`} className="field-error">{t(error, { min: schema.minimum ?? schema.minItems, max: schema.maximum ?? schema.maxItems })}</span> : null}
    </div>
  )
}

/** Set by the batch plan, never typed by the user */
const HIDDEN = new Set(['patient_folders'])

export function SchemaForm({ schema, values, errors, onChange }: { schema: unknown; values: Record<string, unknown>; errors: Record<string, string>; onChange: (v: Record<string, unknown>) => void }) {
  const { t } = useTranslation()
  const [advanced, setAdvanced] = useState(false)
  const [left, setLeft] = useState<ReadonlySet<string>>(new Set())
  const all = fields(schema).filter((f) => !HIDDEN.has(f.name))
  const basic = all.filter((f) => !f.schema['x-advanced'])
  const more = all.filter((f) => f.schema['x-advanced'])
  const set = (name: string) => (v: unknown) => onChange({ ...values, [name]: v })
  const leave = (name: string) => () => setLeft((s) => (s.has(name) ? s : new Set(s).add(name)))
  if (!all.length) return <p className="muted">{t('tasks.noSettings')}</p>
  const field = (f: (typeof all)[number]) => (
    <Field key={f.name} name={f.name} schema={f.schema} required={f.required} value={values[f.name]} error={left.has(f.name) ? errors[f.name] : undefined} onChange={set(f.name)} onLeave={leave(f.name)} />
  )
  return (
    <div className="task-form">
      {basic.map(field)}
      {more.length ? (
        <button type="button" className="btn btn-sm" aria-expanded={advanced} onClick={() => setAdvanced((a) => !a)}>
          {t(advanced ? 'tasks.hideAdvanced' : 'tasks.showAdvanced', { count: more.length })}
        </button>
      ) : null}
      {advanced ? more.map(field) : null}
    </div>
  )
}
