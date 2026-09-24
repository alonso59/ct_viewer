// Filters and feature classes (RAD-02): checkboxes; each class expands to per-feature checkboxes.
// IBSI names and codes are never shown (RADIOMICS §Principles).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Tooltip } from '../../lib'
import { Icon, codicon } from '../../theme'
import { OptionField } from './OptionField'
import { defaultFeatures, setFeatures, setFilter } from './model/settings'
import { fieldOf } from './model/validate'
import type { FormState, Issue, SettingsSchema } from './model/types'
import { IssueText } from './IssueText'

type Props = { schema: SettingsSchema; form: FormState; onChange: (f: FormState) => void; issuesAt: (field: string) => Issue[] }

function Issues({ list }: { list: Issue[] }) {
  return (
    <>
      {list.map((i) => (
        <IssueText key={`${i.rule}-${fieldOf(i.loc)}`} issue={i} className={i.severity === 'error' ? 'field-error' : 'field-warning'} />
      ))}
    </>
  )
}

export function FiltersForm({ schema, form, onChange, issuesAt }: Props) {
  const { t } = useTranslation()
  return (
    <div className="rad-list">
      {schema.filters.map((f) => {
        const s = form.filters[f.name]
        const on = s?.enabled === true
        const id = `rad-filter-${f.name}`
        const box = (
          <label className="check" htmlFor={id}>
            <input id={id} type="checkbox" checked={on} disabled={!f.available && !on} onChange={(e) => onChange(setFilter(form, f.name, { enabled: e.target.checked }))} />
            <span className="mono">{f.name}</span>
          </label>
        )
        return (
          <div key={f.name} className="rad-block" data-on={on || undefined}>
            <div className="rad-block-row">
              {f.available ? box : <Tooltip label={f.unavailable_reason ?? t('rad.unavailable')}>{box}</Tooltip>}
              {f.default_enabled ? <span className="badge">{t('rad.engineDefault')}</span> : null}
              {f.requires_2d ? <span className="badge">{t('rad.needs2d')}</span> : null}
              {!f.available ? <span className="badge" data-tone="warn">{t('rad.unavailable')}</span> : null}
            </div>
            <Issues list={issuesAt(`image_types.${f.name}`)} />
            {on && f.params?.length ? (
              <div className="rad-params">
                {f.params.map((p) => (
                  <OptionField
                    key={p.name}
                    o={p}
                    value={s.params[p.name] ?? null}
                    issues={issuesAt(`image_types.${f.name}.${p.name}`)}
                    onChange={(v) => onChange(setFilter(form, f.name, { params: { [p.name]: v } }))}
                  />
                ))}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

export function FeatureClassesForm({ schema, form, onChange, issuesAt }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState<string | null>(null)
  return (
    <div className="rad-list">
      <Issues list={issuesAt('features')} />
      {schema.feature_classes.map((c) => {
        const picked = form.features[c.name] ?? []
        const all = c.features.map((f) => f.name)
        const on = picked.length > 0
        const expanded = open === c.name
        return (
          <div key={c.name} className="rad-block" data-on={on || undefined}>
            <div className="rad-block-row">
              <input
                type="checkbox"
                aria-label={c.name}
                checked={on}
                ref={(el) => {
                  if (el) el.indeterminate = on && picked.length < all.length
                }}
                onChange={(e) => onChange(setFeatures(form, c.name, e.target.checked ? defaultFeatures(c) : []))}
              />
              <button type="button" className="link rad-class-name" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : c.name)}>
                <Icon spec={codicon(expanded ? 'chevron-down' : 'chevron-right')} />
                <span className="mono">{c.name}</span>
              </button>
              <span className="muted num">{t('rad.featureCount', { n: picked.length, total: all.length })}</span>
              {c.requires_2d ? <span className="badge">{t('rad.needs2d')}</span> : null}
            </div>
            <Issues list={issuesAt(`features.${c.name}`)} />
            {expanded ? (
              <div className="rad-features">
                <div className="rad-features-actions">
                  <button type="button" className="link" onClick={() => onChange(setFeatures(form, c.name, [...all]))}>{t('rad.selectAll')}</button>
                  <button type="button" className="link" onClick={() => onChange(setFeatures(form, c.name, defaultFeatures(c)))}>{t('rad.selectDefaults')}</button>
                  <button type="button" className="link" onClick={() => onChange(setFeatures(form, c.name, []))}>{t('rad.selectNone')}</button>
                </div>
                {c.features.map((f) => (
                  <label key={f.name} className="check">
                    <input
                      type="checkbox"
                      checked={picked.includes(f.name)}
                      onChange={(e) => onChange(setFeatures(form, c.name, e.target.checked ? [...picked, f.name] : picked.filter((x) => x !== f.name)))}
                    />
                    <span className="mono">{f.name}</span>
                    {f.deprecated ? <span className="muted rad-help">{t('rad.deprecated')}</span> : null}
                  </label>
                ))}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
