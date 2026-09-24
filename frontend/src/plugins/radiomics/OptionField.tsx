// One schema option (API-30 OptionSpec) as an input (RAD-02): checkbox, number, select, text or list.
// Label and help text come from the engine schema; the engine default is shown next to the field.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { IconButton } from '../../lib'
import { codicon } from '../../theme'
import { parseList } from './model/settings'
import type { Issue, OptionSpec, Value } from './model/types'
import { IssueText } from './IssueText'

const isList = (o: OptionSpec) => o.type === 'float_list' || o.type === 'int_list'

export function fmtValue(v: Value): string {
  if (v === null) return ''
  if (Array.isArray(v)) return v.join(', ')
  return String(v)
}

const same = (a: Value, b: Value) => JSON.stringify(a) === JSON.stringify(b)

/** List input keeps the typed text; the parsed value is pushed on every change */
function ListInput({ o, value, onChange, id, invalid, disabled }: { o: OptionSpec; value: Value; onChange: (v: Value) => void; id: string; invalid: boolean; disabled?: boolean }) {
  const { t } = useTranslation()
  const [text, setText] = useState(() => fmtValue(value))
  const [pushed, setPushed] = useState<Value>(value)
  // A value set from outside (profile load, reset) replaces the text
  if (!same(value, pushed)) {
    setPushed(value)
    setText(fmtValue(value))
  }
  return (
    <input
      id={id}
      className="input input-sm"
      type="text"
      inputMode="decimal"
      disabled={disabled}
      aria-invalid={invalid || undefined}
      value={text}
      placeholder={o.nullable ? t('rad.none') : t('rad.listPlaceholder')}
      onChange={(e) => {
        const parsed = parseList(e.target.value, o.type === 'int_list')
        const v: Value = parsed ?? (o.nullable ? null : [])
        setText(e.target.value)
        setPushed(v)
        onChange(v)
      }}
    />
  )
}

function NumberInput({ o, value, onChange, id, invalid, disabled }: { o: OptionSpec; value: Value; onChange: (v: Value) => void; id: string; invalid: boolean; disabled?: boolean }) {
  const { t } = useTranslation()
  const [text, setText] = useState(() => fmtValue(value))
  const [pushed, setPushed] = useState<Value>(value)
  if (!same(value, pushed)) {
    setPushed(value)
    setText(fmtValue(value))
  }
  const c = o.constraints
  return (
    <input
      id={id}
      className="input input-sm rad-num"
      type="number"
      step={o.type === 'int' ? 1 : 'any'}
      min={c?.min ?? undefined}
      max={c?.max ?? undefined}
      disabled={disabled}
      aria-invalid={invalid || undefined}
      value={text}
      placeholder={o.nullable ? t('rad.none') : undefined}
      onChange={(e) => {
        const raw = e.target.value
        const v: Value = raw.trim() === '' ? null : Number(raw)
        setText(raw)
        setPushed(v)
        onChange(v)
      }}
    />
  )
}

export function OptionField({ o, value, onChange, issues, disabled }: { o: OptionSpec; value: Value; onChange: (v: Value) => void; issues: Issue[]; disabled?: boolean }) {
  const { t } = useTranslation()
  const id = `rad-opt-${o.group}-${o.name}`
  const invalid = issues.some((i) => i.severity === 'error')
  const def = (o.default ?? null) as Value
  const changed = !same(value, def)
  const reset = changed ? (
    <IconButton label={t('rad.resetOption', { value: fmtValue(def) || t('rad.none') })} icon={codicon('discard')} onClick={() => onChange(def)} disabled={disabled} />
  ) : null
  const meta = (
    <>
      {o.description ? <span className="muted rad-help">{o.description}</span> : null}
      <span className="muted rad-help mono" data-testid={`default-${o.name}`}>{t('rad.defaultIs', { value: fmtValue(def) || t('rad.none') })}</span>
      {issues.map((i) => (
        <IssueText key={`${i.rule}-${i.loc.join('.')}`} issue={i} className={i.severity === 'error' ? 'field-error' : 'field-warning'} />
      ))}
    </>
  )

  if (o.type === 'bool')
    return (
      <div className="rad-opt rad-field" data-changed={changed || undefined}>
        <span className="rad-label mono">{o.name}</span>
        <div className="field">
          <label className="check" htmlFor={id}>
            <input id={id} type="checkbox" checked={value === true} disabled={disabled} aria-invalid={invalid || undefined} onChange={(e) => onChange(e.target.checked)} />
            <span>{value === true ? t('rad.on') : t('rad.off')}</span>
            {reset}
          </label>
          {meta}
        </div>
      </div>
    )

  let input
  if (o.type === 'enum')
    input = (
      <select
        id={id}
        className="select input-sm"
        disabled={disabled}
        aria-invalid={invalid || undefined}
        value={value === null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      >
        {o.nullable ? <option value="">{t('rad.none')}</option> : null}
        {(o.constraints?.enum ?? []).map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    )
  else if (o.type === 'int' || o.type === 'float') input = <NumberInput o={o} value={value} onChange={onChange} id={id} invalid={invalid} disabled={disabled} />
  else if (isList(o)) input = <ListInput o={o} value={value} onChange={onChange} id={id} invalid={invalid} disabled={disabled} />
  else
    input = (
      <input id={id} className="input input-sm" type="text" disabled={disabled} aria-invalid={invalid || undefined} value={value === null ? '' : String(value)} onChange={(e) => onChange(e.target.value)} />
    )

  return (
    <div className="rad-opt rad-field" data-changed={changed || undefined}>
      <label className="rad-label mono" htmlFor={id}>{o.name}</label>
      <div className="field">
        <span className="rad-input-row">
          {input}
          {reset}
        </span>
        {meta}
      </div>
    </div>
  )
}
