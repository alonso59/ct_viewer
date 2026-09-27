// Search view: advanced filters on phase, status, warnings, VOI and any visible study variable
// (VAR-10; `var.{name}` list filters, API.md §Conventions). Applies to the Project view.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { API_MODE, CASE_ROLLUPS, PHASES, useCases, useVariables, type Variable } from '../../api'
import { useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { ItemFilterChip } from './ProjectView'
import { activeFilterCount, useExplorer } from './store'
import { filterable, isCategorical, parseRange, rangeValue } from './vars'

function Select({ label, value, options, onChange }: { label: string; value: string | undefined; options: { v: string; l: string }[]; onChange: (v: string) => void }) {
  const { t } = useTranslation()
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select className="select" value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t('search.any')}</option>
        {options.map((o) => (
          <option key={o.v} value={o.v}>
            {o.l}
          </option>
        ))}
      </select>
    </label>
  )
}

function RangeFilter({ v, value, onChange }: { v: Variable; value: string | undefined; onChange: (spec: string) => void }) {
  const { t } = useTranslation()
  const [min, max] = parseRange(value)
  const [lo, setLo] = useState(min)
  const [hi, setHi] = useState(max)
  const commit = (a: string, b: string) => onChange(rangeValue(a.trim(), b.trim()))
  const hint = v.profile.min != null && v.profile.max != null ? t('search.rangeHint', { min: v.profile.min, max: v.profile.max }) : ''
  return (
    <div className="field">
      <span className="field-label" title={hint}>{v.name}</span>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input className="input input-sm num" inputMode="decimal" aria-label={t('search.min', { name: v.name })} placeholder={v.profile.min != null ? String(v.profile.min) : t('search.minShort')} value={lo} onChange={(e) => setLo(e.target.value)} onBlur={() => commit(lo, hi)} onKeyDown={(e) => e.key === 'Enter' && commit(lo, hi)} style={{ width: '100%' }} />
        <span className="muted">{t('search.to')}</span>
        <input className="input input-sm num" inputMode="decimal" aria-label={t('search.max', { name: v.name })} placeholder={v.profile.max != null ? String(v.profile.max) : t('search.maxShort')} value={hi} onChange={(e) => setHi(e.target.value)} onBlur={() => commit(lo, hi)} onKeyDown={(e) => e.key === 'Enter' && commit(lo, hi)} style={{ width: '100%' }} />
      </div>
    </div>
  )
}

export function SearchView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { filter, setFilter, setVarFilter, clearFilter } = useExplorer()
  const matches = useCases(pid, filter)
  const vars = filterable(useVariables(pid).data ?? [])
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '0 12px 12px' }}>
      {filter.itemIds ? <ItemFilterChip ids={filter.itemIds} /> : null}
      <label className="field">
        <span className="field-label">{t('search.text')}</span>
        <input className="input" value={filter.q ?? ''} placeholder={t('explorer.filterPlaceholder')} onChange={(e) => setFilter({ q: e.target.value })} />
      </label>
      <Select label={t('search.phase')} value={filter.phase} options={PHASES.map((p) => ({ v: p, l: t('search.phaseOption', { code: p, name: t(`phase.${p}`) }) }))} onChange={(phase) => setFilter({ phase })} />
      <Select label={t('search.status')} value={filter.status} options={CASE_ROLLUPS.map((s) => ({ v: s, l: t(`status.${s}`) }))} onChange={(status) => setFilter({ status })} />
      <Select label={t('search.warnings')} value={filter.warning} options={[{ v: 'any', l: t('search.hasWarnings') }, { v: 'none', l: t('search.noWarnings') }]} onChange={(w) => setFilter({ warning: w as 'any' | 'none' | '' })} />
      <Select label={t('search.voi')} value={filter.voi} options={[{ v: 'any', l: t('search.hasVoi') }, { v: 'none', l: t('search.noVoi') }]} onChange={(v) => setFilter({ voi: v as 'any' | 'none' | '' })} />
      <div className="search-section">
        <span className="field-label">{t('search.variables')}</span>
        {vars.length === 0 ? (
          <span className="muted panel-size">{t('search.noVariables')}</span>
        ) : null}
      </div>
      {vars.map((v) =>
        isCategorical(v) ? (
          <Select
            key={v.name}
            label={v.name}
            value={filter.vars?.[v.name]}
            options={(v.profile.levels ?? []).map((l) => ({ v: l.value, l: t('search.levelOption', { value: l.value, count: l.count }) }))}
            onChange={(value) => setVarFilter(v.name, value)}
          />
        ) : (
          // Keyed by the committed value, so clearing filters elsewhere resets the inputs
          <RangeFilter key={`${v.name}:${filter.vars?.[v.name] ?? ''}`} v={v} value={filter.vars?.[v.name]} onChange={(spec) => setVarFilter(v.name, spec)} />
        ),
      )}
      {API_MODE === 'mock' ? (
        <label className="check">
          <input type="checkbox" checked={filter.showExcluded === true} onChange={(e) => setFilter({ showExcluded: e.target.checked })} />
          {t('search.showExcluded')}
        </label>
      ) : null}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="muted">{t('explorer.caseCount', { count: matches.data?.length ?? 0 })}</span>
        <span className="grow" />
        <button type="button" className="btn btn-sm" disabled={activeFilterCount(filter) === 0 && !filter.q} onClick={clearFilter}>
          {t('explorer.clearFilters')}
        </button>
        <button type="button" className="btn btn-sm btn-primary" onClick={() => useLayout.getState().showView('project')}>
          {t('search.showInProject')}
        </button>
      </div>
    </div>
  )
}
