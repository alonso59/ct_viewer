// Search view: advanced filters (group, phase, status, warnings, VOI). Applies to the Project view.
import { useTranslation } from 'react-i18next'

import { CURATION_STATUSES, PHASES, useCases } from '../../api'
import { useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { activeFilterCount, useExplorer } from './store'

export function SearchView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { filter, setFilter, clearFilter } = useExplorer()
  const all = useCases(pid, { showExcluded: true })
  const matches = useCases(pid, filter)
  const groups = [...new Set((all.data ?? []).map((c) => c.group).filter(Boolean))]
  const select = (label: string, value: string | undefined, options: { v: string; l: string }[], on: (v: string) => void) => (
    <label className="field">
      <span className="field-label">{label}</span>
      <select className="select" value={value ?? ''} onChange={(e) => on(e.target.value)}>
        <option value="">{t('search.any')}</option>
        {options.map((o) => (
          <option key={o.v} value={o.v}>
            {o.l}
          </option>
        ))}
      </select>
    </label>
  )
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '0 12px 12px' }}>
      <label className="field">
        <span className="field-label">{t('search.text')}</span>
        <input className="input" value={filter.q ?? ''} placeholder={t('explorer.filterPlaceholder')} onChange={(e) => setFilter({ q: e.target.value })} />
      </label>
      {select(t('search.group'), filter.group, groups.map((g) => ({ v: g, l: g })), (group) => setFilter({ group }))}
      {select(t('search.phase'), filter.phase, PHASES.map((p) => ({ v: p, l: `${p} · ${t(`phase.${p}`)}` })), (phase) => setFilter({ phase }))}
      {select(t('search.status'), filter.status, CURATION_STATUSES.map((s) => ({ v: s, l: t(`status.${s}`) })), (status) => setFilter({ status }))}
      {select(t('search.warnings'), filter.warning, [{ v: 'any', l: t('search.hasWarnings') }, { v: 'none', l: t('search.noWarnings') }], (w) => setFilter({ warning: w as 'any' | 'none' | '' }))}
      {select(t('search.voi'), filter.voi, [{ v: 'any', l: t('search.hasVoi') }, { v: 'none', l: t('search.noVoi') }], (v) => setFilter({ voi: v as 'any' | 'none' | '' }))}
      <label className="check">
        <input type="checkbox" checked={filter.showExcluded === true} onChange={(e) => setFilter({ showExcluded: e.target.checked })} />
        {t('search.showExcluded')}
      </label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="muted">{t('explorer.caseCount', { count: matches.data?.length ?? 0 })}</span>
        <span style={{ flex: 1 }} />
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
