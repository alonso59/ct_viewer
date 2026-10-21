// Search and Project share their filter controls and Explorer state (VAR-10).
import { useTranslation } from 'react-i18next'

import { useCases } from '../../api'
import { useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { FilterFields, PhaseFilter } from './FilterControls'
import { ItemFilterChip } from './ProjectView'
import { activeFilterCount, useExplorer } from './store'

export function SearchView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { filter, setFilter, clearFilter } = useExplorer()
  const matches = useCases(pid, filter)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '0 12px 12px' }}>
      {filter.itemIds ? <ItemFilterChip ids={filter.itemIds} /> : null}
      <label className="field">
        <span className="field-label">{t('search.text')}</span>
        <input className="input" value={filter.q ?? ''} placeholder={t('explorer.filterPlaceholder')} onChange={(e) => setFilter({ q: e.target.value })} />
      </label>
      <PhaseFilter />
      <FilterFields />
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
