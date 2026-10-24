import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, type ItemFilter, type ItemPage } from '../../api'
import { ProblemCard } from '../../lib'
import { parseIds } from './model'

type Row = ItemPage['items'][number]
const filename = (row: Row) => row.image?.ref.split('/').pop()?.replace(/^[^:]+:/, '') || row.item_id
const PAGE_SIZES = [50, 100, 200, 500]

function SelectionBox({ ids, selected, label, disabled, onChange }: { ids: string[]; selected: Set<string>; label: string; disabled: boolean; onChange: (ids: string[], checked: boolean) => void }) {
  const count = ids.filter((id) => selected.has(id)).length
  return <input type="checkbox" aria-label={label} checked={!!ids.length && count === ids.length} disabled={disabled || !ids.length} ref={(node) => { if (node) node.indeterminate = count > 0 && count < ids.length }} onChange={(e) => onChange(ids, e.target.checked)} />
}

export function ItemPicker({ pid, value, onChange, onBusyChange }: { pid: string; value: string; onChange: (value: string) => void; onBusyChange?: (busy: boolean) => void }) {
  const { t } = useTranslation()
  const [filters, setFilters] = useState<ItemFilter>({})
  const [search, setSearch] = useState('')
  const [cursors, setCursors] = useState<string[]>([])
  const [pageSize, setPageSize] = useState(50)
  const [selectionIntent, setSelectionIntent] = useState<boolean | null>(null)
  const selecting = selectionIntent !== null
  const [selectionError, setSelectionError] = useState<unknown>(null)
  const [bulk, setBulk] = useState<{ key: string; ids: string[] } | null>(null)
  const version = useRef(0)
  const grid = useRef<HTMLDivElement>(null)
  const [grouped, setGrouped] = useState(true)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const selected = useMemo(() => new Set(parseIds(value)), [value])
  useEffect(() => () => { version.current++; onBusyChange?.(false) }, [onBusyChange])
  useEffect(() => { if (grid.current) grid.current.scrollTop = 0 }, [filters, pageSize, cursors])
  useEffect(() => {
    if (search.trim() === (filters.q ?? '')) return
    const timer = setTimeout(() => {
      setFilters((old) => old.q === search.trim() ? old : { ...old, q: search.trim() || undefined })
      setCursors([])
    }, 250)
    return () => clearTimeout(timer)
  }, [search, filters.q])
  const filter: ItemFilter = { ...filters, cursor: cursors.at(-1), limit: pageSize }
  const { data, error, isFetching } = useQuery({ queryKey: keys.items(pid, filter), queryFn: () => api.listItems(pid, filter), retry: false })
  const selectionPending = isFetching || search.trim() !== (filters.q ?? '')
  const rows = data?.items ?? []
  const groups = new Map<string, Row[]>()
  for (const row of rows) {
    const key = grouped ? row.case_id : ''
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(row)
  }
  const update = (patch: Partial<ItemFilter>) => { setFilters({ ...filters, ...patch }); setCursors([]) }
  const toggle = (ids: string[], checked: boolean) => {
    const next = new Set(selected)
    for (const id of ids) { if (checked) next.add(id); else next.delete(id) }
    onChange([...next].join('\n'))
  }
  const collapse = (key: string) => setCollapsed((old) => {
    const next = new Set(old)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })
  const pageIds = rows.map((row) => row.item_id)
  const filterKey = JSON.stringify(filters)
  const matchingIds = bulk?.key === filterKey ? bulk.ids : null
  const allChecked = !!matchingIds?.length && matchingIds.length === data?.total && matchingIds.every((id) => selected.has(id))
  const someChecked = (matchingIds ?? pageIds).some((id) => selected.has(id))
  const selectAll = async (checked: boolean) => {
    const current = ++version.current
    setSelectionIntent(checked); onBusyChange?.(true); setSelectionError(null)
    try {
      const ids = await api.listItemIds(pid, filters)
      if (current !== version.current) return
      setBulk({ key: filterKey, ids })
      toggle(ids, checked)
    } catch (e) {
      if (current === version.current) setSelectionError(e)
    } finally {
      if (current === version.current) { setSelectionIntent(null); onBusyChange?.(false) }
    }
  }
  return (
    <fieldset className="task-picker" disabled={selecting} aria-label={t('tasks.pick.table')}>
      <div className="task-picker-filters">
        <label className="task-picker-search"><span>{t('tasks.pick.search')}</span><input className="input" type="search" value={search} placeholder={t('tasks.pick.searchHint')} onChange={(e) => setSearch(e.target.value)} /></label>
        <label><span>{t('tasks.pick.scope')}</span><select className="select" value={filters.scope ?? ''} onChange={(e) => update({ scope: (e.target.value || undefined) as ItemFilter['scope'] })}><option value="">{t('tasks.pick.any')}</option><option value="complete">{t('tasks.pick.complete')}</option><option value="voi">{t('tasks.pick.voi')}</option></select></label>
        <label><span>{t('tasks.pick.phase')}</span><input className="input" value={filters.phase ?? ''} placeholder={t('tasks.pick.any')} onChange={(e) => update({ phase: e.target.value || undefined })} /></label>
        <label><span>{t('tasks.pick.modality')}</span><input className="input" value={filters.modality ?? ''} placeholder={t('tasks.pick.any')} onChange={(e) => update({ modality: e.target.value || undefined })} /></label>
        <label><span>{t('tasks.pick.masks')}</span><select className="select" value={filters.has_mask === undefined ? '' : String(filters.has_mask)} onChange={(e) => update({ has_mask: e.target.value ? e.target.value === 'true' : undefined })}><option value="">{t('tasks.pick.any')}</option><option value="false">{t('tasks.pick.noMasks')}</option><option value="true">{t('tasks.pick.hasMasks')}</option></select></label>
      </div>
      <div className="task-picker-summary">
        <label className="task-picker-all"><input type="checkbox" aria-label={t('tasks.pick.all')} checked={selectionIntent ?? allChecked} ref={(node) => { if (node) node.indeterminate = !selecting && !allChecked && someChecked }} disabled={selectionPending || !data?.total} onChange={(e) => void selectAll(e.target.checked)} />{t('tasks.pick.all')}</label>
        <strong className="num" role="status">{t('tasks.pick.selected', { count: selected.size })}</strong>
        <button className="btn btn-sm" type="button" disabled={!selected.size} onClick={() => onChange('')}>{t('tasks.pick.clear')}</button>
        <label className="task-picker-group"><input type="checkbox" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} />{t('tasks.pick.group')}</label>
      </div>
      <p className="muted task-help">{t('tasks.pick.help')}</p>
      {selecting ? <p role="status" className="muted">{t('tasks.pick.selecting')}</p> : null}
      {error || selectionError ? <ProblemCard error={error ?? selectionError} /> : null}
      <div ref={grid} className="task-picker-grid" aria-busy={selectionPending || selecting}>
        <table aria-label={t('tasks.pick.table')}>
          <thead><tr>
            <th><SelectionBox ids={pageIds} selected={selected} label={t('tasks.pick.pageSelect')} disabled={selectionPending} onChange={toggle} /></th>
            <th>{t('tasks.pick.file')}</th><th>{t('tasks.pick.scan')}</th><th>{t('tasks.pick.phase')}</th><th>{t('tasks.pick.modality')}</th><th>{t('tasks.pick.scope')}</th><th>{t('tasks.pick.masks')}</th>
          </tr></thead>
          {[...groups].map(([caseId, items]) => (
            <tbody key={caseId}>
              {grouped ? <tr className="task-picker-case">
                <td><SelectionBox ids={items.map((row) => row.item_id)} selected={selected} label={t('tasks.pick.caseSelect', { caseId })} disabled={selectionPending} onChange={toggle} /></td>
                <th scope="rowgroup" colSpan={6}><button type="button" aria-expanded={!collapsed.has(caseId)} onClick={() => collapse(caseId)}><span aria-hidden="true">{collapsed.has(caseId) ? '▸' : '▾'}</span> {caseId} <span className="muted">{t('tasks.pick.groupCount', { count: items.length })}</span></button></th>
              </tr> : null}
              {(!grouped || !collapsed.has(caseId)) ? items.map((row) => <tr key={row.item_id} data-selected={selected.has(row.item_id)}>
                <td><SelectionBox ids={[row.item_id]} selected={selected} label={t('tasks.pick.fileSelect', { file: filename(row) })} disabled={selectionPending} onChange={toggle} /></td>
                <td title={`${row.item_id}\n${row.image?.ref ?? ''}`}><span className="task-picker-filename">{filename(row)}</span>{!grouped ? <span className="muted task-help">{row.case_id}</span> : null}</td>
                <td className="num">{row.scan_idx}</td><td>{row.phase.canonical}</td><td>{row.modality ?? '—'}</td><td>{row.scope}</td><td>{Object.keys(row.masks ?? {}).join(', ') || '—'}</td>
              </tr>) : null}
            </tbody>
          ))}
        </table>
        {!rows.length ? <p className="empty">{t(isFetching ? 'common.loading' : 'tasks.pick.empty')}</p> : null}
      </div>
      <div className="task-picker-pagination">
        <span className="muted num">{t('tasks.pick.pageCount', { count: rows.length, total: data?.total ?? 0 })}</span>
        <label className="task-picker-size">{t('tasks.pick.pageSize')}<select className="select" value={pageSize} onChange={(e) => { const size = Number(e.target.value); if (PAGE_SIZES.includes(size)) { setPageSize(size); setCursors([]) } }}>{PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}</select></label>
        <button type="button" className="btn btn-sm" disabled={!cursors.length || isFetching} onClick={() => setCursors((old) => old.slice(0, -1))}>{t('tasks.pick.previous')}</button>
        <button type="button" className="btn btn-sm" disabled={!data?.next_cursor || isFetching} onClick={() => setCursors((old) => [...old, data!.next_cursor!])}>{t('tasks.pick.next')}</button>
      </div>
      <details className="task-picker-manual"><summary>{t('tasks.pick.manual')}</summary><textarea aria-label={t('tasks.pick.manual')} className="input mono" rows={3} value={value} placeholder={t('tasks.listHelp')} onChange={(e) => onChange(e.target.value)} /></details>
    </fieldset>
  )
}
