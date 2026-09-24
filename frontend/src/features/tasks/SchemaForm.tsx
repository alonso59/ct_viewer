// The generic settings form (TSK-02, UI-20): boolean, number, integer, string (enum → select).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { fields, type FieldSchema } from './schema'

function Field({ name, schema, value, error, onChange }: { name: string; schema: FieldSchema; value: unknown; error?: string; onChange: (v: unknown) => void }) {
  const { t } = useTranslation()
  const id = `task-field-${name}`
  let input
  if (schema.type === 'boolean') {
    input = <input id={id} type="checkbox" checked={Boolean(value ?? schema.default)} onChange={(e) => onChange(e.target.checked)} />
  } else if (schema.enum) {
    input = (
      <select id={id} className="select" value={String(value ?? schema.default ?? '')} onChange={(e) => onChange(e.target.value || undefined)}>
        {schema.default === undefined ? <option value="">{t('tasks.fromProject')}</option> : null}
        {schema.enum.map((o) => (
          <option key={String(o)} value={String(o)}>{String(o)}</option>
        ))}
      </select>
    )
  } else if (schema.type === 'integer' || schema.type === 'number') {
    input = (
      <input
        id={id}
        className="input num"
        type="number"
        step={schema.type === 'integer' ? 1 : 'any'}
        min={schema.minimum}
        max={schema.maximum}
        placeholder={schema.default === undefined ? '' : String(schema.default)}
        value={typeof value === 'number' ? value : ''}
        onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
      />
    )
  } else {
    input = (
      <input id={id} className="input mono" placeholder={schema.default === undefined ? '' : String(schema.default)} value={typeof value === 'string' ? value : ''} onChange={(e) => onChange(e.target.value || undefined)} />
    )
  }
  return (
    <div className="task-field">
      <label className="field-label" htmlFor={id}>{name}</label>
      {input}
      {schema['x-help'] ? <span className="muted task-help">{schema['x-help']}</span> : null}
      {error ? <span className="field-error">{t(error, { min: schema.minimum, max: schema.maximum })}</span> : null}
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
