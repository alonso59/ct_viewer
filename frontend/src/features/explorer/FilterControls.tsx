// Shared Explorer filters: Search and the Project panel use the same state.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { API_MODE, CASE_ROLLUPS, PHASES, useProject, useVariables, type Variable } from '../../api'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { useExplorer } from './store'
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

export function PhaseFilter() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { filter, setFilter } = useExplorer()
  const vocabulary = useProject(pid).data?.phase_vocabulary ?? []
  const phases = vocabulary.length ? PHASES.filter((p) => vocabulary.includes(p)) : PHASES
  return <Select label={t('search.phase')} value={filter.phase} options={phases.map((p) => ({ v: p, l: t('search.phaseOption', { code: p, name: t(`phase.${p}`) }) }))} onChange={(phase) => setFilter({ phase })} />
}

export function FilterFields() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { filter, setFilter, setVarFilter } = useExplorer()
  const vars = filterable(useVariables(pid).data ?? [])
  return (
    <>
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
    </>
  )
}

/** Case-level conditions stay visible even when the filter panel is collapsed. */
export function ActiveFilterChips() {
  const { t } = useTranslation()
  const { filter, setFilter, setVarFilter } = useExplorer()
  const chips: { key: string; label: string; clear: () => void }[] = []
  if (filter.phase) chips.push({ key: 'phase', label: `${t('search.phase')}: ${filter.phase}`, clear: () => setFilter({ phase: '' }) })
  if (filter.status) chips.push({ key: 'status', label: `${t('search.status')}: ${t(`status.${filter.status}`)}`, clear: () => setFilter({ status: '' }) })
  if (filter.warning) chips.push({ key: 'warning', label: t(filter.warning === 'any' ? 'search.hasWarnings' : 'search.noWarnings'), clear: () => setFilter({ warning: '' }) })
  if (filter.voi) chips.push({ key: 'voi', label: t(filter.voi === 'any' ? 'search.hasVoi' : 'search.noVoi'), clear: () => setFilter({ voi: '' }) })
  if (filter.showExcluded) chips.push({ key: 'excluded', label: t('search.showExcluded'), clear: () => setFilter({ showExcluded: false }) })
  for (const [name, value] of Object.entries(filter.vars ?? {})) {
    if (value) chips.push({ key: `var.${name}`, label: `${name}: ${value}`, clear: () => setVarFilter(name, '') })
  }
  if (!chips.length) return null
  return (
    <div className="pv-filter-chips" aria-label={t('explorer.activeFilters')}>
      {chips.map((chip) => (
        <span key={chip.key} className="badge item-filter-chip" title={chip.label}>
          <span className="pv-chip-label">{chip.label}</span>
          <button type="button" className="icon-btn pv-chip-close" aria-label={t('explorer.removeFilter', { filter: chip.label })} onClick={chip.clear}>
            <Icon spec={codicon('close')} />
          </button>
        </span>
      ))}
    </div>
  )
}
