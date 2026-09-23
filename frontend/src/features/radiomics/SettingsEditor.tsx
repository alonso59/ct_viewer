// Radiomics settings tab: generated from the engine schema (RAD-01/02), live validation (RAD-04),
// profiles (RAD-03), selection (RAD-05), estimate (RAD-11) and the Run button. Nothing runs automatically.
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  api,
  defaultSettings,
  useProfiles,
  useProject,
  useSaveProfile,
  useSchema,
  useStartRun,
  validateSettings,
  ReviewerCancelled,
  type Settings,
  type SettingsGroup,
  type SettingsOption,
} from '../../api'
import { fmtDuration } from '../../lib'
import { toast, useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { Icon, codicon } from '../../theme'
import './radiomics.css'

function parseList(v: string, int: boolean): number[] | null {
  if (!v.trim()) return null
  return v
    .split(/[,\s]+/)
    .filter(Boolean)
    .map((x) => (int ? parseInt(x, 10) : parseFloat(x)))
    .filter((x) => Number.isFinite(x))
}

function OptionInput({ o, value, onChange, error, disabled }: { o: SettingsOption; value: unknown; onChange: (v: unknown) => void; error?: string; disabled?: boolean }) {
  const { t } = useTranslation()
  const id = `opt-${o.key}`
  if (o.type === 'bool')
    return (
      <label className="check rad-opt" htmlFor={id} data-child={o.parent ? 'true' : undefined}>
        <input id={id} type="checkbox" checked={value === true} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
        <span>{o.title}</span>
        {o.help ? <span className="muted rad-help">{o.help}</span> : null}
        {error ? <span className="field-error">{error}</span> : null}
      </label>
    )
  const common = { id, disabled, 'aria-invalid': error ? true : undefined, className: 'input input-sm' }
  let input
  if (o.type === 'select')
    input = (
      <select {...common} className="select input-sm" value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
        {o.choices?.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    )
  else if (o.type === 'int' || o.type === 'float')
    input = (
      <input
        {...common}
        type="number"
        step={o.type === 'int' ? 1 : 'any'}
        min={o.min}
        max={o.max}
        value={value === null || value === undefined ? '' : String(value)}
        placeholder={o.nullable ? t('radiomics.none') : undefined}
        onChange={(e) => onChange(e.target.value === '' ? null : o.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value))}
      />
    )
  else if (o.type === 'float_list' || o.type === 'int_list')
    input = (
      <input
        {...common}
        type="text"
        value={Array.isArray(value) ? value.join(', ') : ''}
        placeholder={o.nullable ? t('radiomics.none') : t('radiomics.listPlaceholder')}
        onChange={(e) => onChange(parseList(e.target.value, o.type === 'int_list'))}
      />
    )
  else input = <input {...common} type="text" value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
  return (
    <div className="rad-opt rad-field" data-child={o.parent ? 'true' : undefined}>
      <label htmlFor={id}>{o.title}</label>
      <div className="field">
        {input}
        {o.help ? <span className="muted rad-help">{o.help}</span> : null}
        {error ? <span className="field-error">{error}</span> : null}
      </div>
    </div>
  )
}

function FeatureClasses({ g, s, set }: { g: SettingsGroup; s: Settings; set: (patch: Settings) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState<string | null>(null)
  return (
    <div className="rad-classes">
      {g.options.map((o) => {
        const cls = o.key.slice('featureClass.'.length)
        const all = g.features?.[cls] ?? []
        const picked = (s[`features.${cls}`] as string[] | undefined) ?? []
        const on = s[o.key] === true
        return (
          <div key={o.key} className="rad-class">
            <div className="rad-class-row">
              <input type="checkbox" aria-label={cls} checked={on} onChange={(e) => set({ [o.key]: e.target.checked })} />
              <button type="button" className="link rad-class-name" onClick={() => setOpen(open === cls ? null : cls)}>
                <Icon spec={codicon(open === cls ? 'chevron-down' : 'chevron-right')} />
                {cls}
              </button>
              <span className="muted num">{t('radiomics.featureCount', { n: on ? picked.length : 0, total: all.length })}</span>
            </div>
            {open === cls ? (
              <div className="rad-features">
                <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8 }}>
                  <button type="button" className="link" onClick={() => set({ [`features.${cls}`]: [...all] })}>{t('radiomics.all')}</button>
                  <button type="button" className="link" onClick={() => set({ [`features.${cls}`]: [] })}>{t('radiomics.noneSel')}</button>
                </div>
                {all.map((f) => (
                  <label key={f} className="check">
                    <input
                      type="checkbox"
                      disabled={!on}
                      checked={picked.includes(f)}
                      onChange={(e) => set({ [`features.${cls}`]: e.target.checked ? [...picked, f] : picked.filter((x) => x !== f) })}
                    />
                    <span className="mono">{f}</span>
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

export function SettingsEditor() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const schema = useSchema()
  const project = useProject(pid)
  const profiles = useProfiles(pid)
  const saveProfile = useSaveProfile(pid)
  const startRun = useStartRun(pid)
  const [s, setS] = useState<Settings>(() => defaultSettings())
  const [openGroup, setOpenGroup] = useState<string>('filters')
  const [scope, setScope] = useState<'complete' | 'voi'>('complete')
  const [labels, setLabels] = useState<number[]>([2])
  const [name, setName] = useState(() => t('radiomics.defaultRunName'))
  const [profileName, setProfileName] = useState('')
  const [estimate, setEstimate] = useState<{ n_extractions: number; sec_per_item: number } | null>(null)
  const set = (patch: Settings) => setS((prev) => ({ ...prev, ...patch }))
  const issues = useMemo(() => validateSettings(s, { labels, items: 1 }), [s, labels])
  const errors = issues.filter((i) => i.severity === 'error')
  const byField = new Map(issues.filter((i) => i.field).map((i) => [i.field, i.message]))

  if (schema.isLoading) return <div className="empty">{t('common.loading')}</div>
  if (!schema.data) return <div className="error-card">{t('common.error')}</div>

  const groupErrors = (g: SettingsGroup) => g.options.filter((o) => byField.has(o.key)).length
  const run = async () => {
    try {
      await startRun.mutateAsync({ name, scope, labels })
      toast({ message: t('radiomics.started', { name }), tone: 'info', action: { label: t('radiomics.showJobs'), run: () => useLayout.getState().showPanelTab('jobs') } })
    } catch (e) {
      if (!(e instanceof ReviewerCancelled)) toast({ message: t('common.saveFailed'), tone: 'error' })
    }
  }

  return (
    <div className="rad">
      <div className="rad-top">
        <div className="rad-top-row">
          <Icon spec={codicon('beaker')} />
          <strong>{t('radiomics.title')}</strong>
          <span className="muted">{t('radiomics.engine', { name: schema.data.engine.name, version: schema.data.engine.version })}</span>
          <span style={{ flex: 1 }} />
          <select
            className="select input-sm"
            aria-label={t('radiomics.loadProfile')}
            value=""
            onChange={(e) => {
              const p = profiles.data?.find((x) => x.name === e.target.value)
              if (p) setS({ ...p.settings })
            }}
          >
            <option value="">{t('radiomics.loadProfile')}</option>
            {profiles.data?.map((p) => (
              <option key={p.name} value={p.name}>{t('radiomics.profileOption', { name: p.name, hash: p.hash })}</option>
            ))}
          </select>
          <button type="button" className="btn btn-sm" onClick={() => setS(defaultSettings(schema.data))}>
            {t('radiomics.resetDefaults')}
          </button>
        </div>
      </div>
      <div className="rad-body">
        <nav className="rad-nav" aria-label={t('radiomics.groups')}>
          <button type="button" className="list-row" aria-selected={openGroup === 'selection'} onClick={() => setOpenGroup('selection')}>
            <Icon spec={codicon('filter')} />
            {t('radiomics.selection')}
          </button>
          {schema.data.groups.map((g) => (
            <button key={g.id} type="button" className="list-row" aria-selected={openGroup === g.id} onClick={() => setOpenGroup(g.id)}>
              <Icon spec={codicon('settings')} />
              {g.title}
              {groupErrors(g) ? <span className="count" style={{ marginLeft: 'auto', background: 'var(--error)', color: 'var(--fg-on-emphasis)' }}>{groupErrors(g)}</span> : null}
            </button>
          ))}
        </nav>
        <div className="rad-form">
          {openGroup === 'selection' ? (
            <section>
              <h2>{t('radiomics.selection')}</h2>
              <div className="rad-field">
                <label>{t('radiomics.items')}</label>
                <select className="select input-sm" defaultValue="active">
                  <option value="active">{t('radiomics.itemsActive')}</option>
                  <option value="filter">{t('radiomics.itemsFilter')}</option>
                  <option value="list">{t('radiomics.itemsList')}</option>
                </select>
              </div>
              <div className="rad-field">
                <label>{t('radiomics.scope')}</label>
                <div className="seg" role="group">
                  <button type="button" aria-pressed={scope === 'complete'} onClick={() => { setScope('complete'); setEstimate(null) }}>{t('item.full')}</button>
                  <button type="button" aria-pressed={scope === 'voi'} onClick={() => { setScope('voi'); setEstimate(null) }}>{t('item.voi')}</button>
                </div>
              </div>
              <div className="rad-field">
                <label>{t('radiomics.labels')}</label>
                <div style={{ display: 'flex', gap: 12 }}>
                  {project.data?.label_map.map((l) => (
                    <label key={l.value} className="check">
                      <input type="checkbox" checked={labels.includes(l.value)} onChange={(e) => { setLabels(e.target.checked ? [...labels, l.value] : labels.filter((x) => x !== l.value)); setEstimate(null) }} />
                      <span className="dot" style={{ background: l.color }} />
                      {l.name}
                    </label>
                  ))}
                </div>
              </div>
            </section>
          ) : null}
          {schema.data.groups
            .filter((g) => g.id === openGroup)
            .map((g) => (
              <section key={g.id}>
                <h2>{g.title}</h2>
                {g.features ? (
                  <FeatureClasses g={g} s={s} set={set} />
                ) : (
                  g.options.map((o) => (
                    <OptionInput
                      key={o.key}
                      o={o}
                      value={s[o.key]}
                      error={byField.get(o.key)}
                      disabled={o.parent ? s[o.parent] !== true : false}
                      onChange={(v) => set({ [o.key]: v })}
                    />
                  ))
                )}
              </section>
            ))}
        </div>
        <aside className="rad-side">
          <div className="section-title" style={{ padding: 0 }}>{t('radiomics.validation')}</div>
          {issues.length === 0 ? (
            <div className="rad-issue" data-severity="ok">
              <Icon spec={codicon('pass')} />
              {t('radiomics.valid')}
            </div>
          ) : (
            issues.map((i) => (
              <div key={`${i.field}-${i.message}`} className="rad-issue" data-severity={i.severity}>
                <Icon spec={codicon(i.severity === 'error' ? 'error' : 'warning')} />
                <span>{i.message}</span>
              </div>
            ))
          )}
          <div className="section-title" style={{ padding: 0, marginTop: 12 }}>{t('radiomics.profile')}</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input className="input input-sm" style={{ flex: 1 }} value={profileName} placeholder={t('radiomics.profileName')} onChange={(e) => setProfileName(e.target.value)} />
            <button
              type="button"
              className="btn btn-sm"
              disabled={!profileName.trim()}
              onClick={() => void saveProfile.mutateAsync({ name: profileName.trim(), settings: s }).then((p) => toast({ message: t('radiomics.profileSaved', { name: p.name, hash: p.hash }), tone: 'ok' }))}
            >
              {t('common.save')}
            </button>
          </div>
          <div className="section-title" style={{ padding: 0, marginTop: 12 }}>{t('radiomics.run')}</div>
          <label className="field">
            <span className="field-label">{t('radiomics.runName')}</span>
            <input className="input input-sm" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <button
            type="button"
            className="btn btn-sm"
            disabled={errors.length > 0}
            onClick={() => void api.estimate(pid, { scope, labels }).then(setEstimate)}
          >
            <Icon spec={codicon('dashboard')} />
            {t('radiomics.estimate')}
          </button>
          {estimate ? (
            <div className="muted" style={{ fontSize: 'var(--fs-panel)' }}>
              {t('radiomics.estimateResult', { n: estimate.n_extractions, time: fmtDuration(estimate.n_extractions * estimate.sec_per_item) })}
            </div>
          ) : null}
          <button type="button" className="btn btn-primary" disabled={errors.length > 0 || !name.trim() || startRun.isPending} onClick={() => void run()}>
            <Icon spec={codicon('play')} />
            {t('radiomics.runButton')}
          </button>
          {errors.length ? <span className="field-error">{t('radiomics.fixErrors', { count: errors.length })}</span> : null}
        </aside>
      </div>
    </div>
  )
}
