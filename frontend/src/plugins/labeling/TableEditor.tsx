// Label table tab (LBL-03..05, 07): a spreadsheet over the table's rows. Arrow keys / Tab move,
// Enter or typing edits, Space toggles yes/no, Delete clears, Shift extends the selection, paste
// takes a TSV block from a spreadsheet, "Fill" writes one value into the selection. Every change
// is a cell event (LBL-04); other reviewers' edits arrive live (SSE, LBL-05).
import { useVirtualizer } from '@tanstack/react-virtual'
import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState, type ClipboardEvent, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, ProblemError, useLabelCells, useLabelHistory, useLabelTables, useProject, type LabelCellIn, type LabelColumn, type LabelImportReport } from '../../api'
import { openItem } from '../../features/explorer'
import { Dialog, ProblemCard } from '../../lib'
import { registry, toast, useWorkbench, type EditorProps } from '../../shell'
import { requireReviewer } from '../../state'
import { Icon, codicon } from '../../theme'
import { display, fillCells, filterRows, move, parseTsv, pasteCells, rect, sortRows, type Pos } from './model'
import { ColumnsForm, toColumns, type Draft } from './NewTableDialog'
import './labeling.css'

export interface TableParams {
  tableId: string
}

const ROW_H = 26

function CellEditor({ col, value, onCommit, onCancel }: { col: LabelColumn; value: unknown; onCommit: (v: unknown) => void; onCancel: () => void }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState(value == null ? '' : String(value))
  const keys = (e: KeyboardEvent) => {
    e.stopPropagation()
    if (e.key === 'Escape') onCancel()
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      onCommit(draft)
    }
  }
  if (col.type === 'category')
    return (
      <select className="lbl-input" autoFocus aria-label={col.name} value={draft} onKeyDown={keys} onChange={(e) => onCommit(e.target.value)} onBlur={onCancel}>
        <option value="">{t('lbl.empty_value')}</option>
        {(col.levels ?? []).map((l) => <option key={l} value={l}>{l}</option>)}
      </select>
    )
  return (
    <input
      className="lbl-input"
      autoFocus
      aria-label={col.name}
      type={col.type === 'number' ? 'number' : col.type === 'date' ? 'date' : 'text'}
      value={draft}
      onKeyDown={keys}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => onCommit(draft)}
    />
  )
}

function History({ pid, tid, target, col }: { pid: string; tid: string; target: string | null; col: LabelColumn | null }) {
  const { t } = useTranslation()
  const h = useLabelHistory(pid, tid, target, col?.column_id ?? null).data ?? []
  if (!target || !col) return null
  return (
    <aside className="lbl-history" aria-label={t('lbl.history')}>
      <strong>{t('lbl.historyOf', { target, col: col.name })}</strong>
      {h.length ? (
        <ol>
          {h.map((e) => (
            <li key={e.event_id}>
              <span className="mono">{display(col, e.value) || t('lbl.cleared')}</span>
              <span className="muted lbl-small">{t('lbl.by', { reviewer: e.reviewer, at: new Date(e.at).toLocaleString() })}</span>
            </li>
          ))}
        </ol>
      ) : <p className="muted lbl-small">{t('lbl.noHistory')}</p>}
    </aside>
  )
}

export default function TableEditor({ params }: EditorProps<TableParams>) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const tid = params.tableId
  const table = useLabelTables(pid).data?.find((x) => x.table_id === tid)
  const cells = useLabelCells(pid, tid)
  const labels = useProject(pid).data?.label_map ?? []
  const readOnly = registry.readOnly
  const cols = useMemo(() => (table?.columns ?? []).filter((c) => !c.hidden), [table])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<{ col: string | null; dir: 1 | -1 }>({ col: null, dir: 1 })
  const rows = useMemo(() => sortRows(filterRows(cells.data?.items ?? [], cols, filters, q), sort.col, sort.dir), [cells.data, cols, filters, q, sort])
  const [active, setActive] = useState<Pos>({ r: 0, c: 0 })
  const [anchor, setAnchor] = useState<Pos | null>(null)
  const [editing, setEditing] = useState<Pos | null>(null)
  const [fill, setFill] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [report, setReport] = useState<LabelImportReport | null>(null)
  const [error, setError] = useState<unknown>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const grid = useRef<HTMLDivElement>(null)
  const picker = useRef<HTMLInputElement>(null)
  // TanStack Virtual is not React-compiler compatible yet (as in the Project view)
  // eslint-disable-next-line react-hooks/incompatible-library
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => ROW_H, overscan: 12, initialRect: { width: 800, height: 600 } })
  const sel = rect(active, anchor ?? active)

  const write = async (list: LabelCellIn[]) => {
    if (readOnly || !list.length) return
    const reviewer = await requireReviewer()
    if (!reviewer) return
    try {
      setError(null)
      await api.writeLabelCells(pid, tid, list, reviewer)
      void qc.invalidateQueries({ queryKey: ['project', pid, 'labeling'] })
    } catch (e) {
      setError(e)
    }
  }
  const commit = (p: Pos, v: unknown) => {
    setEditing(null)
    const row = rows[p.r]
    const col = cols[p.c]
    if (!row || !col) return
    const cur = row.values?.[col.column_id]
    if ((v === '' ? null : v) === (cur ?? null) || String(v) === String(cur ?? '')) return
    void write([{ column_id: col.column_id, target: row.target, value: v === '' ? null : v }])
    setActive(move(p, 'Enter', rows.length, cols.length))
    grid.current?.focus()
  }
  const goto = (p: Pos, extend: boolean) => {
    setActive(p)
    setAnchor(extend ? (anchor ?? active) : null)
    virt.scrollToIndex(p.r)
  }
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (editing || !rows.length || !cols.length) return
    const col = cols[active.c]
    const row = rows[active.r]
    if (e.key.startsWith('Arrow') || e.key === 'Tab') {
      e.preventDefault()
      goto(move(active, e.key === 'Tab' && e.shiftKey ? 'ArrowLeft' : e.key, rows.length, cols.length), e.shiftKey && e.key !== 'Tab')
    } else if ((e.key === 'Enter' || e.key === 'F2') && !readOnly) {
      e.preventDefault()
      if (col?.type === 'bool' && row) void write([{ column_id: col.column_id, target: row.target, value: !row.values?.[col.column_id] }])
      else setEditing(active)
    } else if (e.key === ' ' && col?.type === 'bool' && row && !readOnly) {
      e.preventDefault()
      void write([{ column_id: col.column_id, target: row.target, value: !row.values?.[col.column_id] }])
    } else if ((e.key === 'Delete' || e.key === 'Backspace') && !readOnly) {
      e.preventDefault()
      void write(fillCells(active, anchor ?? active, null, rows, cols))
    } else if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !readOnly && col?.type !== 'bool') {
      setEditing(active)
    }
  }
  const onPaste = (e: ClipboardEvent<HTMLDivElement>) => {
    if (readOnly || editing) return
    e.preventDefault()
    void write(pasteCells(parseTsv(e.clipboardData.getData('text/plain')), active, rows, cols))
  }
  const onImport = async (file: File | undefined) => {
    if (!file) return
    const reviewer = await requireReviewer()
    if (!reviewer) return
    try {
      setReport(await api.importLabelTable(pid, tid, file, reviewer))
      void qc.invalidateQueries({ queryKey: ['project', pid, 'labeling'] })
    } catch (e) {
      setError(e)
    }
  }

  if (!table) return <div className="page"><p className="muted">{t('common.loading')}</p></div>
  const selectedCol = cols[active.c] ?? null
  const selectedRow = rows[active.r] ?? null
  return (
    <div className="lbl-editor" data-table={table.slug}>
      <div className="lbl-toolbar" role="toolbar" aria-label={t('lbl.toolbar')}>
        <strong>{table.name}</strong>
        <span className="badge">{t(`lbl.level.${table.level}`)}</span>
        <input className="input input-sm" aria-label={t('lbl.findRow')} placeholder={t('lbl.findRow')} value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted lbl-small">{t('lbl.rowsShown', { n: rows.length, total: cells.data?.total ?? 0 })}</span>
        {readOnly ? (
          <span className="badge" data-tone="accent">{t('lbl.readOnly')}</span>
        ) : (
          <>
            <button type="button" className="btn btn-sm" onClick={() => setFill('')}>{t('lbl.fill')}</button>
            <button type="button" className="btn btn-sm" onClick={() => setAdding(true)}>{t('lbl.addCol')}</button>
            <button type="button" className="btn btn-sm" onClick={() => picker.current?.click()}>{t('lbl.import')}</button>
            <input ref={picker} type="file" accept=".csv,.tsv,.txt" hidden aria-label={t('lbl.import')} onChange={(e) => void onImport(e.target.files?.[0])} />
          </>
        )}
        <a className="btn btn-sm" href={api.labelExportUrl(pid, tid, 'csv')} download>{t('lbl.export')}</a>
      </div>
      {error ? <ProblemCard error={error instanceof ProblemError ? error : new Error(String(error))} /> : null}
      <div className="lbl-body">
        <div
          ref={grid}
          className="lbl-grid"
          role="grid"
          aria-label={table.name}
          aria-rowcount={rows.length}
          tabIndex={0}
          onKeyDown={onKey}
          onPaste={onPaste}
          style={{ gridTemplateColumns: `180px repeat(${cols.length}, minmax(110px, 1fr))` }}
        >
          <div className="lbl-head" role="row">
            <button type="button" role="columnheader" className="lbl-th" onClick={() => setSort({ col: '__target', dir: sort.col === '__target' ? (-sort.dir as 1 | -1) : 1 })}>
              {t(`lbl.level.${table.level}`)}
            </button>
            {cols.map((c) => (
              <button key={c.column_id} type="button" role="columnheader" className="lbl-th" title={c.description ?? ''} onClick={() => setSort({ col: c.column_id, dir: sort.col === c.column_id ? (-sort.dir as 1 | -1) : 1 })}>
                {c.name}
                {sort.col === c.column_id ? <Icon spec={codicon(sort.dir === 1 ? 'arrow-up' : 'arrow-down')} /> : null}
              </button>
            ))}
          </div>
          <div className="lbl-head lbl-filters" role="row">
            <span className="lbl-th muted lbl-small">{t('lbl.filter')}</span>
            {cols.map((c) => (
              <input key={c.column_id} className="lbl-filter" aria-label={t('lbl.filterCol', { name: c.name })} value={filters[c.column_id] ?? ''} onChange={(e) => setFilters({ ...filters, [c.column_id]: e.target.value })} />
            ))}
          </div>
          <div ref={scroller} className="lbl-scroll">
            <div style={{ height: virt.getTotalSize(), position: 'relative' }}>
              {virt.getVirtualItems().map((v) => {
                const row = rows[v.index]!
                return (
                  <div key={row.target} role="row" className="lbl-tr" style={{ transform: `translateY(${v.start}px)`, height: ROW_H, gridTemplateColumns: `180px repeat(${cols.length}, minmax(110px, 1fr))` }}>
                    <span role="rowheader" className="lbl-target mono">
                      {row.target}
                      {row.item_id ? (
                        <button type="button" className="icon-btn" aria-label={t('lbl.openViewer', { target: row.target })} onClick={() => openItem(row.case_id, row.item_id ?? null, false)}>
                          <Icon spec={codicon('eye')} />
                        </button>
                      ) : null}
                    </span>
                    {cols.map((c, ci) => {
                      const at = { r: v.index, c: ci }
                      const selected = at.r >= sel.r0 && at.r <= sel.r1 && at.c >= sel.c0 && at.c <= sel.c1
                      const isActive = active.r === at.r && active.c === at.c
                      const value = row.values?.[c.column_id]
                      return (
                        <div
                          key={c.column_id}
                          role="gridcell"
                          aria-selected={selected}
                          data-active={isActive}
                          className="lbl-td"
                          title={row.updated?.[c.column_id] ? t('lbl.lastBy', { reviewer: row.updated[c.column_id] }) : undefined}
                          onMouseDown={(e) => goto(at, e.shiftKey)}
                          onDoubleClick={() => !readOnly && c.type !== 'bool' && setEditing(at)}
                        >
                          {editing && editing.r === at.r && editing.c === at.c ? (
                            <CellEditor col={c} value={value} onCommit={(nv) => commit(at, nv)} onCancel={() => { setEditing(null); grid.current?.focus() }} />
                          ) : (
                            display(c, value)
                          )}
                        </div>
                      )
                    })}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
        <History pid={pid} tid={tid} target={selectedRow?.target ?? null} col={selectedCol} />
      </div>
      {fill !== null ? (
        <Dialog
          open
          onOpenChange={(o) => !o && setFill(null)}
          title={t('lbl.fillTitle', { n: (sel.r1 - sel.r0 + 1) * (sel.c1 - sel.c0 + 1) })}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setFill(null)}>{t('common.cancel')}</button>
              <button type="button" className="btn btn-primary" onClick={() => { void write(fillCells(active, anchor ?? active, fill || null, rows, cols)); setFill(null) }}>{t('lbl.fill')}</button>
            </>
          }
        >
          <label className="field">
            <span className="field-label">{t('lbl.fillValue')}</span>
            <input className="input" autoFocus value={fill} onChange={(e) => setFill(e.target.value)} />
            <span className="muted lbl-small">{t('lbl.fillHelp')}</span>
          </label>
        </Dialog>
      ) : null}
      {adding ? <AddColumns pid={pid} tid={tid} labels={labels.map((l) => l.name)} onClose={() => setAdding(false)} /> : null}
      {report ? (
        <Dialog open onOpenChange={(o) => !o && setReport(null)} title={t('lbl.importTitle')}>
          <p>{t('lbl.importReport', { matched: report.matched, n: report.n_rows, events: report.n_events, key: report.key })}</p>
          {report.columns?.length ? <p className="muted">{t('lbl.importCols', { list: report.columns.join(', ') })}</p> : null}
          {report.ignored_columns?.length ? <p className="muted">{t('lbl.importIgnored', { list: report.ignored_columns.join(', ') })}</p> : null}
          {report.unmatched?.length ? <p className="muted">{t('lbl.importUnmatched', { list: report.unmatched.slice(0, 20).join(', ') })}</p> : null}
          {report.errors?.length ? <p className="muted">{t('lbl.importErrors', { list: report.errors.slice(0, 10).join('; ') })}</p> : null}
        </Dialog>
      ) : null}
    </div>
  )
}

function AddColumns({ pid, tid, labels, onClose }: { pid: string; tid: string; labels: string[]; onClose: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [drafts, setDrafts] = useState<Draft[]>([{ name: '', type: 'bool', levels: '', unit: '' }])
  const save = async () => {
    try {
      await api.patchLabelTable(pid, tid, { columns: toColumns(drafts) })
      void qc.invalidateQueries({ queryKey: keys.labelTables(pid) })
      void qc.invalidateQueries({ queryKey: keys.labelCells(pid, tid) })
      onClose()
    } catch (e) {
      toast({ message: e instanceof ProblemError ? (e.detail ?? e.title) : String(e), tone: 'error' })
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('lbl.addCol')} footer={<><button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button><button type="button" className="btn btn-primary" onClick={() => void save()}>{t('common.save')}</button></>}>
      <ColumnsForm drafts={drafts} setDrafts={setDrafts} labels={labels} />
    </Dialog>
  )
}
