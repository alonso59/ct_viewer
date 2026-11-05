import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, useCohortBalance, useCohortRows, useCohortSummary, useCohortTimeline, useLabelTables, useVariables, type CohortCaseRow, type CohortScanRow, type Variable } from '../../api'
import { ContingencyMap, EventTimeline, ValueSummary } from '../../plugins/dashboard'
import { registry, toastProblem, useWorkbench } from '../../shell'
import { requireReviewer } from '../../state'
import { Icon, codicon } from '../../theme'
import { DicomTags } from '../viewer'
import { CATEGORIES, ORIGINS, useCohort } from './store'

/** A panel's title bar with its close button */
function PanelHead({ title, onClose }: { title: string; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="cohort-panel-head">
      <strong>{title}</strong>
      <button type="button" className="icon-btn" aria-label={t('cohort.panel.close', { title })} title={t('cohort.panel.close', { title })} onClick={onClose}>
        <Icon spec={codicon('close')} />
      </button>
    </div>
  )
}

/** The focused column over the filtered rows; a click on a bar or bin adds that filter */
export function SummaryPanel({ column }: { column: string }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const filters = useCohort((s) => s.filters)
  const addVarValue = useCohort((s) => s.addVarValue)
  const setSummary = useCohort((s) => s.setSummary)
  const query = useCohortSummary(pid, column, filters.vars)
  return (
    <section className="cohort-panel" aria-label={t('cohort.summary.title', { name: column })}>
      <PanelHead title={t('cohort.summary.title', { name: column })} onClose={() => setSummary(null)} />
      <ValueSummary name={column} summary={query.data} query={query} onPick={(value) => addVarValue(column, value)} />
    </section>
  )
}

const scanLabel = (s: CohortScanRow) => `${s.scan_idx} · ${s.phase} · ${s.modality ?? '—'}`

const sameAcross = (c: CohortCaseRow, name: string) => !c.differs?.includes(name)

/** The scans of one case side by side: variables as rows (grouped as the navigator), scans as columns */
export function ComparePanel({ caseId }: { caseId: string }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const vars = useVariables(pid).data
  const setCompare = useCohort((s) => s.setCompare)
  const [differencesOnly, setDifferencesOnly] = useState(false)
  const shown = useMemo(() => (vars ?? []).filter((v) => v.type !== 'constant'), [vars])
  const req = useMemo(() => ({ columns: shown.map((v) => v.name), q: caseId, sort: null, offset: 0, limit: 50 }), [shown, caseId])
  const rows = useCohortRows(pid, shown.length ? req : null)
  const row = rows.data?.rows?.find((r) => r.case_id === caseId)
  const groups = useMemo(() => {
    const out: { key: string; label: string; vars: Variable[] }[] = []
    for (const origin of ORIGINS) {
      const inOrigin = shown.filter((v) => v.origin === origin)
      if (origin !== 'metadata') {
        if (inOrigin.length) out.push({ key: origin, label: t(`cohort.nav.group.${origin}`), vars: inOrigin })
        continue
      }
      for (const category of CATEGORIES) {
        const inCategory = inOrigin.filter((v) => v.category === category)
        if (inCategory.length) out.push({ key: category, label: t(`cohort.nav.category.${category}`), vars: inCategory })
      }
    }
    return out
  }, [shown, t])
  const title = t('cohort.compare.title', { caseId })
  return (
    <section className="cohort-panel" aria-label={title}>
      <PanelHead title={title} onClose={() => setCompare(null)} />
      <label className="cohort-toggle">
        <input type="checkbox" checked={differencesOnly} onChange={(e) => setDifferencesOnly(e.target.checked)} />
        {t('cohort.compare.differencesOnly')}
      </label>
      {!row ? (
        <div className="empty">{rows.isLoading ? t('common.loading') : t('cohort.compare.none')}</div>
      ) : (
        <div className="cohort-compare" tabIndex={0} role="region" aria-label={t('cohort.compare.fields')}>
          <table className="table small">
            <thead>
              <tr>
                <th scope="col">{t('cohort.compare.field')}</th>
                {row.scans?.map((s) => (
                  <th key={s.scan_idx} scope="col">{scanLabel(s)}</th>
                ))}
              </tr>
            </thead>
            {groups.map((g) => {
              const list = g.vars.filter((v) => !differencesOnly || !sameAcross(row, v.name))
              if (!list.length) return null
              return (
                <tbody key={g.key}>
                  <tr><th scope="rowgroup" colSpan={(row.scans?.length ?? 0) + 1} className="cohort-compare-group">{g.label}</th></tr>
                  {list.map((v) => (
                    <tr key={v.name}>
                      <th scope="row" className="mono">{v.name}</th>
                      {row.scans?.map((s) => <td key={s.scan_idx}>{s.values?.[v.name] ?? '—'}</td>)}
                    </tr>
                  ))}
                </tbody>
              )
            })}
          </table>
        </div>
      )}
    </section>
  )
}

/** One scan's DICOM tags, read only once this panel is open */
export function TagsPanel({ itemId }: { itemId: string }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const setTags = useCohort((s) => s.setTags)
  const [search, setSearch] = useState('')
  const title = t('cohort.tags.title', { itemId })
  return (
    <section className="cohort-panel" aria-label={title}>
      <PanelHead title={title} onClose={() => setTags(null)} />
      <input className="input input-sm" value={search} placeholder={t('cohort.tags.search')} aria-label={t('cohort.tags.search')} onChange={(e) => setSearch(e.target.value)} />
      <div className="cohort-tags">
        <DicomTags pid={pid} iid={itemId} search={search} />
      </div>
    </section>
  )
}

/** Two categorical variables over the filtered rows: counts, and the test that compares them */
export function BalancePanel({ a, b }: { a: string; b: string }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const filters = useCohort((s) => s.filters)
  const setBalance = useCohort((s) => s.setBalance)
  const categorical = (useVariables(pid).data ?? []).filter((v) => v.type === 'categorical')
  const query = useCohortBalance(pid, a && b && a !== b ? { a, b, filters: filters.vars, test: 'auto' } : null)
  const title = t('cohort.balance.title')
  const pick = (which: 'a' | 'b', label: string) => (
    <label className="cohort-toggle">
      {label}
      <select className="select input-sm" value={which === 'a' ? a : b} onChange={(e) => setBalance(which === 'a' ? { a: e.target.value, b } : { a, b: e.target.value })}>
        <option value="" />
        {categorical.map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}
      </select>
    </label>
  )
  return (
    <section className="cohort-panel" aria-label={title}>
      <PanelHead title={title} onClose={() => setBalance(null)} />
      <div className="cohort-balance-pick">
        {pick('a', t('cohort.balance.rows'))}
        {pick('b', t('cohort.balance.cols'))}
      </div>
      {a && b && a !== b ? <ContingencyMap name={`${a}-by-${b}`} balance={query.data} query={query} /> : <div className="empty">{t('cohort.balance.pick')}</div>}
    </section>
  )
}

/** A case's scans and events on a day axis, and a form that adds an event to an event table */
export function TimelinePanel({ caseId }: { caseId: string }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const setTimeline = useCohort((s) => s.setTimeline)
  const timeline = useCohortTimeline(pid, caseId)
  const tables = (useLabelTables(pid).data ?? []).filter((x) => x.level === 'event')
  const [tableId, setTableId] = useState('')
  const table = tables.find((x) => x.table_id === tableId) ?? tables[0]
  const kindCol = table?.columns?.find((c) => c.slug === 'kind')
  const dayCol = table?.columns?.find((c) => c.slug === 'day')
  const [kind, setKind] = useState('')
  const [day, setDay] = useState('')
  const readOnly = registry.readOnly
  const title = t('cohort.timeline.title', { caseId })
  const refresh = () => {
    for (const part of ['labeling', 'cohort'] as const) void qc.invalidateQueries({ queryKey: keys.scope(pid, part) })
    void qc.invalidateQueries({ queryKey: keys.variables(pid) })
  }
  const add = async () => {
    const reviewer = await requireReviewer()
    if (!reviewer || !table || !kindCol || !dayCol) return
    try {
      const row = await api.addLabelRow(pid, table.table_id, caseId, reviewer)
      const cells = [{ column_id: kindCol.column_id, target: row.target, value: kind || kindCol.levels?.[0] || null }, { column_id: dayCol.column_id, target: row.target, value: day.trim().replace(',', '.') || null }]
      await api.writeLabelCells(pid, table.table_id, cells, reviewer)
      setDay('')
    } catch (e) {
      toastProblem(e)
    }
    refresh()
  }
  const remove = async (tid: string, target: string) => {
    const reviewer = await requireReviewer()
    if (!reviewer) return
    try {
      await api.removeLabelRow(pid, tid, target, reviewer)
    } catch (e) {
      toastProblem(e)
    }
    refresh()
  }
  return (
    <section className="cohort-panel" aria-label={title}>
      <PanelHead title={title} onClose={() => setTimeline(null)} />
      {timeline.data ? <EventTimeline timeline={timeline.data} /> : <div className="empty">{timeline.isError ? t('cohort.timeline.failed') : t('common.loading')}</div>}
      <ul className="cohort-events" aria-label={t('cohort.timeline.events')}>
        {(timeline.data?.events ?? []).map((e) => (
          <li key={e.target}>
            <span>{t('cohort.timeline.eventLine', { kind: e.kind ?? '—', day: e.day ?? '—', table: e.table })}</span>
            {readOnly ? null : (
              <button type="button" className="icon-btn" aria-label={t('cohort.timeline.remove', { kind: e.kind ?? '—', day: e.day ?? '—' })} onClick={() => void remove(e.table_id, e.target)}>
                <Icon spec={codicon('trash')} />
              </button>
            )}
          </li>
        ))}
      </ul>
      {readOnly ? null : table && kindCol && dayCol ? (
        <div className="cohort-event-form">
          {tables.length > 1 ? (
            <select className="select input-sm" aria-label={t('cohort.timeline.table')} value={table.table_id} onChange={(e) => setTableId(e.target.value)}>
              {tables.map((x) => <option key={x.table_id} value={x.table_id}>{x.name}</option>)}
            </select>
          ) : null}
          <select className="select input-sm" aria-label={t('cohort.timeline.kind')} value={kind || kindCol.levels?.[0] || ''} onChange={(e) => setKind(e.target.value)}>
            {(kindCol.levels ?? []).map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
          <input className="input input-sm" inputMode="decimal" aria-label={t('cohort.timeline.dayField')} placeholder={t('cohort.timeline.dayField')} value={day} onChange={(e) => setDay(e.target.value)} />
          <button type="button" className="btn btn-sm" disabled={!day.trim()} onClick={() => void add()}>{t('cohort.timeline.add')}</button>
        </div>
      ) : (
        <p className="muted">{t('cohort.timeline.noTable')}</p>
      )}
    </section>
  )
}
