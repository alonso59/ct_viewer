import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { PHASES, useProject } from '../../api'
import { showFiltersInExplorer } from '../explorer'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { useCohort } from './store'

/** The text filter's input; remounted on the committed value, which resets the draft */
function TextFilter({ value, onCommit }: { value: string; onCommit: (q: string) => void }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState(value)
  const label = t('cohort.filters.text')
  const commit = () => {
    const q = draft.trim()
    if (q !== value) onCommit(q)
  }
  return (
    <input
      className="input input-sm"
      value={draft}
      placeholder={label}
      aria-label={label}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => e.key === 'Enter' && commit()}
      onBlur={commit}
    />
  )
}

/** The grid's filters: text and phase inputs, the active filters as removable chips */
export function FilterBar() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const vocabulary = useProject(pid).data?.phase_vocabulary ?? []
  const filters = useCohort((s) => s.filters)
  const removeVarValue = useCohort((s) => s.removeVarValue)
  const setPhase = useCohort((s) => s.setPhase)
  const setQ = useCohort((s) => s.setQ)
  const clearFilters = useCohort((s) => s.clearFilters)
  const setBalance = useCohort((s) => s.setBalance)
  const phases = vocabulary.length ? PHASES.filter((p) => vocabulary.includes(p)) : PHASES
  const chips: { key: string; label: string; clear: () => void }[] = []
  for (const [name, values] of Object.entries(filters.vars))
    for (const value of values)
      chips.push({ key: `${name}:${value}`, label: t('search.chip', { name, value }), clear: () => removeVarValue(name, value) })
  if (filters.phase) chips.push({ key: 'phase', label: t('search.chip', { name: t('search.phase'), value: filters.phase }), clear: () => setPhase('') })
  if (filters.q) chips.push({ key: 'q', label: t('search.chip', { name: t('cohort.filters.text'), value: filters.q }), clear: () => setQ('') })
  const send = () =>
    // The Explorer keeps one value per variable; a variable with several values sends its first
    showFiltersInExplorer({
      vars: Object.fromEntries(Object.entries(filters.vars).map(([n, vs]) => [n, vs[0] ?? '']).filter(([, value]) => value !== '')),
      phase: filters.phase,
      q: filters.q,
    })
  return (
    <div className="cohort-filter-bar">
      <TextFilter key={filters.q} value={filters.q} onCommit={setQ} />
      <select className="select input-sm" aria-label={t('search.phase')} value={filters.phase} onChange={(e) => setPhase(e.target.value)}>
        <option value="">{t('search.any')}</option>
        {phases.map((p) => (
          <option key={p} value={p}>{t('search.phaseOption', { code: p, name: t(`phase.${p}`) })}</option>
        ))}
      </select>
      {chips.map((chip) => (
        <span key={chip.key} className="badge item-filter-chip" title={chip.label}>
          <span className="pv-chip-label">{chip.label}</span>
          <button type="button" className="icon-btn pv-chip-close" aria-label={t('explorer.removeFilter', { filter: chip.label })} onClick={chip.clear}>
            <Icon spec={codicon('close')} />
          </button>
        </span>
      ))}
      <button type="button" className="btn btn-sm" onClick={() => setBalance({ a: '', b: '' })}>{t('cohort.balance.open')}</button>
      {chips.length ? (
        <>
          <button type="button" className="btn btn-sm" onClick={clearFilters}>{t('explorer.clearFilters')}</button>
          <button type="button" className="btn btn-sm" onClick={send}>{t('cohort.filters.send')}</button>
        </>
      ) : null}
    </div>
  )
}
