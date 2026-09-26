// Inspector section "Labels · this case / scan" (AUD-A1-05, LBL-03/04): for every label table, the
// cells of the row the viewer shows (case, its scan or the item, by the table's level), with the
// table's own cell editors; each change is a cell event (LBL-04), others' edits arrive live (LBL-05).
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ProblemError, useItem, useLabelCells, useLabelTables, type ItemRecord, type LabelColumn, type LabelTableInfo } from '../../api'
import { openEditor, registry, toast, useWorkbench } from '../../shell'
import { requireReviewer, useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { CellEditor } from './CellEditor'
import { display } from './model'
import './labeling.css'

/** The row a table has for the case on screen (LBL-01 levels); null without an item for scan/item tables */
export function targetOf(level: LabelTableInfo['level'], caseId: string, item: Pick<ItemRecord, 'item_id' | 'scan_idx'> | undefined): string | null {
  if (level === 'case') return caseId
  if (!item) return null
  return level === 'scan' ? `${caseId}.${item.scan_idx}` : item.item_id
}

function Cell({ pid, tid, target, col, value }: { pid: string; tid: string; target: string; col: LabelColumn; value: unknown }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const readOnly = registry.readOnly || Boolean(col.ref)
  const write = async (v: unknown) => {
    setEditing(false)
    const next = v === '' ? null : v
    if (next === (value ?? null) || String(next ?? '') === String(value ?? '')) return
    const reviewer = await requireReviewer()
    if (!reviewer) return
    try {
      await api.writeLabelCells(pid, tid, [{ column_id: col.column_id, target, value: next }], reviewer)
      void qc.invalidateQueries({ queryKey: ['project', pid, 'labeling'] })
    } catch (e) {
      toast({ message: e instanceof ProblemError ? (e.detail ?? e.title) : t('common.saveFailed'), tone: 'error' })
    }
  }
  if (col.type === 'bool' && !col.ref)
    return <input type="checkbox" aria-label={col.name} checked={value === true} disabled={readOnly} onChange={() => void write(!value)} />
  if (editing) return <CellEditor col={col} value={value} onCommit={(v) => void write(v)} onCancel={() => setEditing(false)} />
  const text = display(col, value)
  if (readOnly) return <span className={text ? undefined : 'muted'} title={col.ref ? t('lbl.refOf', { name: col.ref }) : undefined}>{text || t('lbl.empty_value')}</span>
  return (
    <button type="button" className="lbl-icell" aria-label={t('lbl.editCell', { col: col.name })} onClick={() => setEditing(true)}>
      {text || <span className="muted">{t('lbl.empty_value')}</span>}
    </button>
  )
}

function TableCells({ pid, table, target }: { pid: string; table: LabelTableInfo; target: string | null }) {
  const { t } = useTranslation()
  const cells = useLabelCells(pid, table.table_id)
  const row = target ? cells.data?.items.find((r) => r.target === target) : undefined
  const cols = (table.columns ?? []).filter((c) => !c.hidden)
  return (
    <div className="lbl-isection" role="group" aria-label={table.name}>
      <div className="lbl-card-head">
        <strong>{table.name}</strong>
        <span className="badge">{t(`lbl.level.${table.level}`)}</span>
        <button type="button" className="icon-btn" aria-label={t('lbl.openTable', { name: table.name })} title={t('lbl.openTable', { name: table.name })} onClick={() => openEditor('labeling', { tableId: table.table_id })}>
          <Icon spec={codicon('table')} />
        </button>
      </div>
      {cells.isLoading ? <span className="muted lbl-small">{t('common.loading')}</span> : !row ? (
        <span className="muted lbl-small">{t('lbl.notARow')}</span>
      ) : (
        cols.map((c) => (
          <div key={c.column_id} className="lbl-irow">
            <span className="muted" title={c.description ?? undefined}>{c.name}</span>
            <Cell pid={pid} tid={table.table_id} target={row.target} col={c} value={row.values?.[c.column_id]} />
          </div>
        ))
      )}
    </div>
  )
}

export default function InspectorLabels() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const caseId = useViewerSync((s) => s.activeCaseId)
  const itemId = useViewerSync((s) => s.activeItemId)
  const item = useItem(pid, itemId).data
  const tables = useLabelTables(pid).data ?? []
  if (!caseId) return <div className="muted lbl-small">{t('lbl.inspectorNoCase')}</div>
  if (!tables.length) return <div className="muted lbl-small">{t('lbl.inspectorNoTables')}</div>
  return (
    <div className="lbl-inspector">
      {tables.map((tb) => (
        <TableCells key={tb.table_id} pid={pid} table={tb} target={targetOf(tb.level, caseId, item)} />
      ))}
    </div>
  )
}
