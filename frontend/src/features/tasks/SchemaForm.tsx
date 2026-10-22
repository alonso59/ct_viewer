// The generic settings form (TSK-02, UI-20): boolean, number, integer, string (enum → select),
// array of enum (→ toggle chips). `title` labels a field, `x-enumNames` names enum values.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { NumberInput } from '../../lib'
import { fields, type FieldSchema } from './schema'

function Field({ name, schema, value, error, onChange }: { name: string; schema: FieldSchema; value: unknown; error?: string; onChange: (v: unknown) => void }) {
  const { t } = useTranslation()
  const id = `task-field-${name}`
  const label = (s: FieldSchema, i: number, o: unknown) => s['x-enumNames']?.[i] ?? String(o)
  let input
  if (schema.type === 'array' && schema.items?.enum) {
    const items = schema.items
    const picked = Array.isArray(value) ? value.map(String) : []
    const full = schema.maxItems !== undefined && picked.length >= schema.maxItems
    const toggle = (o: string) => onChange(picked.includes(o) ? picked.filter((p) => p !== o) : [...picked, o])
    input = (
      <div className="task-chips">
        <span id={id} role="group" aria-labelledby={`${id}-label`} className="seg">
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
    input = <input id={id} type="checkbox" checked={Boolean(value ?? schema.default)} onChange={(e) => onChange(e.target.checked)} />
  } else if (schema.enum) {
    input = (
      <select id={id} className="select" value={String(value ?? schema.default ?? '')} onChange={(e) => onChange(e.target.value || undefined)}>
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
        onChange={(n, raw) => onChange(raw.trim() === '' ? undefined : (n ?? Number.NaN))}
      />
    )
  } else {
    input = (
      <input id={id} className="input mono" placeholder={schema.default === undefined ? '' : String(schema.default)} value={typeof value === 'string' ? value : ''} onChange={(e) => onChange(e.target.value || undefined)} />
    )
  }
  return (
    <div className="task-field">
      <label id={`${id}-label`} className="field-label" htmlFor={id}>{schema.title ?? name}</label>
      {input}
      {schema['x-help'] ? <span className="muted task-help">{schema['x-help']}</span> : null}
      {error ? <span className="field-error">{t(error, { min: schema.minimum ?? schema.minItems, max: schema.maximum ?? schema.maxItems })}</span> : null}
    </div>
  )
}

export function SchemaForm({ schema, values, errors, onChange }: { schema: unknown; values: Record<string, unknown>; errors: Record<string, string>; onChange: (v: Record<string, unknown>) => void }) {
  const { t } = useTranslation()
  const [advanced, setAdvanced] = useState(false)
  const all = fields(schema)
  const basic = all.filter((f) => !f.schema['x-advanced'])
  const more = all.filter((f) => f.schema['x-advanced'])
  const set = (name: string) => (v: unknown) => onChange({ ...values, [name]: v })
  if (!all.length) return <p className="muted">{t('tasks.noSettings')}</p>
  return (
    <div className="task-form">
      {basic.map((f) => <Field key={f.name} name={f.name} schema={f.schema} value={values[f.name]} error={errors[f.name]} onChange={set(f.name)} />)}
      {more.length ? (
        <button type="button" className="btn btn-sm" aria-expanded={advanced} onClick={() => setAdvanced((a) => !a)}>
          {t(advanced ? 'tasks.hideAdvanced' : 'tasks.showAdvanced', { count: more.length })}
        </button>
      ) : null}
      {advanced ? more.map((f) => <Field key={f.name} name={f.name} schema={f.schema} value={values[f.name]} error={errors[f.name]} onChange={set(f.name)} />) : null}
    </div>
  )
}
