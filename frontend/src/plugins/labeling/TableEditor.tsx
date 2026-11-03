// Label table tab: a spreadsheet over the table's rows. Arrow keys / Tab move, Enter or typing
// edits, Space toggles yes/no, Delete clears, Shift extends the selection, paste takes a TSV block
// from a spreadsheet, "Fill" writes one value into the selection, Ctrl/Cmd+Z reverts the last edit.
import { useVirtualizer } from '@tanstack/react-virtual'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type ClipboardEvent, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, ProblemError, useLabelCells, useLabelHistory, useLabelTables, useProject, type LabelCellIn, type LabelColumn, type LabelImportReport, type LabelTable } from '../../api'
import { openInContext } from '../../features/explorer'
import { Dialog, ProblemCard, toolbarKeyDown } from '../../lib'
import { registry, toast, useWorkbench, type EditorProps, toastProblem } from '../../shell'
import { requireReviewer } from '../../state'
import { Icon, codicon } from '../../theme'
import { display, fillCells, filterRows, move, parseTsv, pasteCells, rect, sortRows, type Pos } from './model'
import { CellEditor } from './CellEditor'
import { ColumnsForm, empty, toColumns, useRefOptions, type Draft } from './NewTableDialog'
import { ColumnMenu, TableMenu } from './TableActions'
import './labeling.css'

export interface TableParams {
  tableId: string
}

const ROW_H = 26

/** The same cell value, as the grid compares them (empty = none) */
const sameValue = (a: unknown, b: unknown) => String(a ?? '') === String(b ?? '')

/** The last edit: what the cells held before and what was written */
interface Edit {
  before: LabelCellIn[]
  after: LabelCellIn[]
}

function History({ pid, tid, target, col }: { pid: string; tid: string; target: string | null; col: LabelColumn | null }) {
  const { t } = useTranslation()
  const h = useLabelHistory(pid, tid, target, col?.ref ? null : (col?.column_id ?? null)).data ?? []
  if (!target || !col) return null
  if (col.ref)
    return (
      <aside className="lbl-history" aria-label={t('lbl.history')}>
        <strong>{t('lbl.historyOf', { target, col: col.name })}</strong>
        <p className="muted lbl-small">{t('lbl.refHistory', { name: col.ref })}</p>
      </aside>
    )
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
  const tables = useLabelTables(pid)
  const table = tables.data?.find((x) => x.table_id === tid)
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
  const [saving, setSaving] = useState<'idle' | 'saving' | 'saved'>('idle')
  const lastEdit = useRef<Edit | null>(null)
  // the import report offers Undo once the import's changes are known
  const [importUndo, setImportUndo] = useState(false)
  // an Undo in a toast runs later: it reads the cells as they are then
  const items = useRef(cells.data?.items)
  useEffect(() => {
    items.current = cells.data?.items
  })
  const valueOf = (c: LabelCellIn) => items.current?.find((r) => r.target === c.target)?.values?.[c.column_id] ?? null
  const scroller = useRef<HTMLDivElement>(null)
  const grid = useRef<HTMLDivElement>(null)
  const picker = useRef<HTMLInputElement>(null)
  // TanStack Virtual is not React-compiler compatible yet
  // eslint-disable-next-line react-hooks/incompatible-library
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => ROW_H, overscan: 12, initialRect: { width: 800, height: 600 } })
  const sel = rect(active, anchor ?? active)

  /** Write cells; an edit (not an undo) is kept so Ctrl/Cmd+Z can revert it */
  const write = async (all: LabelCellIn[], undoing = false) => {
    // reference columns are read-only: paste, fill and Delete skip them
    const refCols = new Set(cols.filter((c) => c.ref).map((c) => c.column_id))
    const list = all.filter((c) => !refCols.has(c.column_id))
    if (readOnly || !list.length) return
    const reviewer = await requireReviewer()
    if (!reviewer) return
    const before = list.map((c) => ({ ...c, value: valueOf(c) }))
    try {
      setError(null)
      setSaving('saving')
      await api.writeLabelCells(pid, tid, list, reviewer)
      setSaving('saved')
      void qc.invalidateQueries({ queryKey: keys.scope(pid, 'labeling') })
    } catch (e) {
      setSaving('idle')
      setError(e)
      return
    }
    lastEdit.current = undoing ? null : { before, after: list }
    // a paste, fill or range delete is easy to make by mistake: it says how to take it back
    if (!undoing && list.length > 1) toast({ message: t('lbl.changedCells', { count: list.length }), action: { label: t('common.undo'), run: () => void revert() } })
  }
  /** Revert the last edit with new cell events; a cell someone changed since keeps their value */
  const revert = async () => {
    const edit = lastEdit.current
    if (!edit) return
    lastEdit.current = null
    const back = edit.before.filter((b, i) => {
      const now = valueOf(b)
      return sameValue(now, edit.after[i]?.value) || sameValue(now, b.value)
    })
    await write(back, true)
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
  // Only keys and pastes on the grid itself: a header menu, sort button or column filter inside it
  // keeps its own keys (Enter on a column menu, letters in a filter) instead of editing a cell
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || editing || !rows.length || !cols.length) return
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') {
      e.preventDefault()
      if (!readOnly) void revert()
      return
    }
    const col = cols[active.c]
    const row = rows[active.r]
    if (e.key.startsWith('Arrow') || e.key === 'Tab') {
      e.preventDefault()
      goto(move(active, e.key === 'Tab' && e.shiftKey ? 'ArrowLeft' : e.key, rows.length, cols.length), e.shiftKey && e.key !== 'Tab')
    } else if (col?.ref) {
      return
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
    if (e.target !== e.currentTarget || readOnly || editing) return
    e.preventDefault()
    void write(pasteCells(parseTsv(e.clipboardData.getData('text/plain')), active, rows, cols))
  }
  const onImport = async (file: File | undefined) => {
    if (!file) return
    const reviewer = await requireReviewer()
    if (!reviewer) return
    const was = items.current ?? []
    try {
      setReport(await api.importLabelTable(pid, tid, file, reviewer))
      await qc.invalidateQueries({ queryKey: keys.scope(pid, 'labeling') })
    } catch (e) {
      setError(e)
      return
    }
    // an import is one edit too: Ctrl/Cmd+Z writes back the cells it changed
    const now = qc.getQueryData<typeof cells.data>(keys.labelCells(pid, tid))?.items ?? []
    const changed = now.flatMap((row) =>
      cols.filter((c) => !c.ref).flatMap((c) => {
        const before = was.find((r) => r.target === row.target)?.values?.[c.column_id] ?? null
        const after = row.values?.[c.column_id] ?? null
        return sameValue(before, after) ? [] : [{ column_id: c.column_id, target: row.target, before, after }]
      }),
    )
    lastEdit.current = changed.length
      ? { before: changed.map((c) => ({ column_id: c.column_id, target: c.target, value: c.before })), after: changed.map((c) => ({ column_id: c.column_id, target: c.target, value: c.after })) }
      : null
    setImportUndo(changed.length > 0)
  }

  // deleted (here or by another reviewer) while the tab was open
  if (!table) return <div className="page"><p className="muted">{t(tables.data ? 'lbl.tableGone' : 'common.loading')}</p></div>
  const selectedCol = cols[active.c] ?? null
  const selectedRow = rows[active.r] ?? null
  const cellId = (r: number, c: number) => `lbl-${tid}-${r}-${c}`
  const sortOf = (col: string) => (sort.col === col ? (sort.dir === 1 ? 'ascending' : 'descending') : undefined)
  return (
    <div className="lbl-editor" data-table={table.slug}>
      <div className="lbl-toolbar" role="toolbar" aria-label={t('lbl.toolbar')} onKeyDown={toolbarKeyDown}>
        <strong>{table.name}</strong>
        <span className="badge">{t(`lbl.level.${table.level}`)}</span>
        {readOnly ? null : <TableMenu pid={pid} table={table} />}
        <input className="input input-sm" aria-label={t('lbl.findRow')} placeholder={t('lbl.findRow')} value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted lbl-small">{t('lbl.rowsShown', { n: rows.length, total: cells.data?.total ?? 0 })}</span>
        {saving === 'idle' ? null : <span className="muted lbl-small">{t(saving === 'saving' ? 'lbl.saving' : 'lbl.saved')}</span>}
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
          aria-rowcount={rows.length + 2}
          // focus stays on the grid; the active cell is its active descendant
          aria-activedescendant={rows[active.r] && cols[active.c] ? cellId(active.r, active.c) : undefined}
          tabIndex={0}
          onKeyDown={onKey}
          onPaste={onPaste}
          style={{ gridTemplateColumns: `180px repeat(${cols.length}, minmax(110px, 1fr))` }}
        >
          <div className="lbl-head" role="row" aria-rowindex={1}>
            <div role="columnheader" className="lbl-th lbl-th-col" aria-sort={sortOf('__target')}>
              <button type="button" className="lbl-sort" onClick={() => setSort({ col: '__target', dir: sort.col === '__target' ? (-sort.dir as 1 | -1) : 1 })}>
                {t(`lbl.level.${table.level}`)}
                {sort.col === '__target' ? <Icon spec={codicon(sort.dir === 1 ? 'arrow-up' : 'arrow-down')} /> : null}
              </button>
            </div>
            {cols.map((c) => (
              <div key={c.column_id} role="columnheader" className="lbl-th lbl-th-col" aria-sort={sortOf(c.column_id)}>
                <button type="button" className="lbl-sort" title={c.ref ? t('lbl.refOf', { name: c.ref }) : (c.description ?? '')} onClick={() => setSort({ col: c.column_id, dir: sort.col === c.column_id ? (-sort.dir as 1 | -1) : 1 })}>
                  {c.ref ? <Icon spec={codicon('link')} /> : null}
                  {c.name}
                  {sort.col === c.column_id ? <Icon spec={codicon(sort.dir === 1 ? 'arrow-up' : 'arrow-down')} /> : null}
                </button>
                {readOnly ? null : <ColumnMenu pid={pid} tid={tid} col={c} />}
              </div>
            ))}
          </div>
          <div className="lbl-head lbl-filters" role="row" aria-rowindex={2}>
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
                  <div key={row.target} role="row" aria-rowindex={v.index + 3} className="lbl-tr" style={{ transform: `translateY(${v.start}px)`, height: ROW_H, gridTemplateColumns: `180px repeat(${cols.length}, minmax(110px, 1fr))` }}>
                    <span role="rowheader" className="lbl-target mono">
                      {row.target}
                      {row.item_id ? (
                        <button type="button" className="icon-btn" aria-label={t('lbl.openViewer', { target: row.target })} onClick={() => openInContext(table.name, rows.map((x) => ({ caseId: x.case_id, itemId: x.item_id ?? null })), v.index, false)}>
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
                          id={cellId(at.r, at.c)}
                          role="gridcell"
                          aria-selected={selected}
                          data-active={isActive}
                          className={c.ref ? 'lbl-td lbl-td-ref' : 'lbl-td'}
                          aria-readonly={c.ref ? true : undefined}
                          title={c.ref ? t('lbl.refOf', { name: c.ref }) : row.updated?.[c.column_id] ? t('lbl.lastBy', { reviewer: row.updated[c.column_id] }) : undefined}
                          onMouseDown={(e) => goto(at, e.shiftKey)}
                          onDoubleClick={() => !readOnly && !c.ref && c.type !== 'bool' && setEditing(at)}
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
      {adding ? <AddColumns pid={pid} tid={tid} level={table.level} labels={labels.map((l) => l.name)} onClose={() => setAdding(false)} /> : null}
      {report ? (
        <Dialog
          open
          onOpenChange={(o) => !o && setReport(null)}
          title={t('lbl.importTitle')}
          footer={importUndo ? <button type="button" className="btn" onClick={() => { setReport(null); setImportUndo(false); void revert() }}>{t('lbl.undoImport')}</button> : undefined}
        >
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

function AddColumns({ pid, tid, level, labels, onClose }: { pid: string; tid: string; level: LabelTable['level']; labels: string[]; onClose: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [drafts, setDrafts] = useState<Draft[]>([empty()])
  const refs = useRefOptions(pid, level)
  const save = async () => {
    try {
      await api.patchLabelTable(pid, tid, { columns: toColumns(drafts) })
      void qc.invalidateQueries({ queryKey: keys.labelTables(pid) })
      void qc.invalidateQueries({ queryKey: keys.labelCells(pid, tid) })
      onClose()
    } catch (e) {
      toastProblem(e)
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('lbl.addCol')} footer={<><button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button><button type="button" className="btn btn-primary" onClick={() => void save()}>{t('common.save')}</button></>}>
      <ColumnsForm drafts={drafts} setDrafts={setDrafts} labels={labels} refs={refs} />
    </Dialog>
  )
}
