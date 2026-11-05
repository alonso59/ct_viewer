import { useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, useLabelTables, type CohortCaseRow, type LabelCellIn, type LabelColumn, type LabelTableInfo } from '../../api'
import { toast, toastProblem } from '../../shell'
import { requireReviewer } from '../../state'

/** A Clinical & labels variable and the label table cell column behind it */
export interface ClinicalColumn {
  table: LabelTableInfo
  col: LabelColumn
}

/** Variables named `lbl.{table}.{column}` map to their table and column; reference columns mirror
 *  another variable and stay read-only */
export function useClinicalColumns(pid: string): Map<string, ClinicalColumn> {
  const tables = useLabelTables(pid).data
  return useMemo(() => {
    const out = new Map<string, ClinicalColumn>()
    for (const table of tables ?? [])
      for (const col of table.columns ?? []) if (!col.hidden && !col.ref) out.set(`lbl.${table.slug}.${col.slug}`, { table, col })
    return out
  }, [tables])
}

/** The table row a grid row stands for, or null when the table's level is not edited from this row:
 *  patient tables edit case rows, scan tables edit scan rows (item tables only in their own tab) */
export function targetOf(c: ClinicalColumn, caseId: string, scanIdx: string | null): string | null {
  if (c.table.level === 'case') return scanIdx === null ? caseId : null
  if (c.table.level === 'scan') return scanIdx === null ? null : `${caseId}.${scanIdx}`
  return null
}

/** Write cells to a label table as events; a toast offers undo (new events that restore the
 *  previous values, unless someone changed a cell since) */
export function useCellWriter(pid: string) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  return async (tableId: string, cells: LabelCellIn[], before: LabelCellIn[]) => {
    const reviewer = await requireReviewer()
    if (!reviewer || cells.length === 0) return
    const refresh = () => {
      void qc.invalidateQueries({ queryKey: keys.scope(pid, 'labeling') })
      void qc.invalidateQueries({ queryKey: keys.scope(pid, 'cohort') })
      void qc.invalidateQueries({ queryKey: keys.variables(pid) })
    }
    try {
      await api.writeLabelCells(pid, tableId, cells, reviewer)
    } catch (e) {
      toastProblem(e)
      return
    }
    refresh()
    toast({
      message: t('cohort.edit.changed', { count: cells.length }),
      tone: 'ok',
      action: {
        label: t('common.undo'),
        run: () => {
          void api.writeLabelCells(pid, tableId, before, reviewer).then(refresh, toastProblem)
        },
      },
    })
  }
}

/** The rows a bulk edit of one clinical column covers, in the grid's order: case rows or scan rows */
interface BulkRow {
  target: string
  caseId: string
  scanIdx: string | null
  value: unknown
}

export function rowsOf(info: ClinicalColumn, name: string, cases: CohortCaseRow[]): BulkRow[] {
  return cases.flatMap((c): BulkRow[] => {
    if (info.table.level === 'case') return [{ target: c.case_id, caseId: c.case_id, scanIdx: null, value: c.values?.[name] }]
    return (c.scans ?? []).map((s) => ({ target: `${c.case_id}.${s.scan_idx}`, caseId: c.case_id, scanIdx: s.scan_idx, value: s.values?.[name] }))
  })
}

/** Clipboard text from a spreadsheet: one value per line (the first column when there are several) */
export const pastedColumn = (text: string): string[] =>
  text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n').map((line) => (line.split('\t')[0] ?? '').trim())
