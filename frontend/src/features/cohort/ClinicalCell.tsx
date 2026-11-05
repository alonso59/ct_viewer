import type { ReactNode } from 'react'

import type { LabelCellIn, Variable } from '../../api'
import { CellEditor } from '../../plugins/labeling'
import { registry, useWorkbench } from '../../shell'
import { targetOf, useCellWriter, type ClinicalColumn } from './clinical'
import { useCohort } from './store'

/** A grid cell that edits in place when it belongs to a Clinical & labels column and the workbench
 *  may write; other cells show their value untouched. Double-click edits (a yes/no cell toggles). */
export function ClinicalCell({ column, info, caseId, scanIdx, value, children }: {
  column: Variable
  info: ClinicalColumn | undefined
  caseId: string
  scanIdx: string | null
  value: unknown
  children: ReactNode
}) {
  const pid = useWorkbench((s) => s.pid) ?? ''
  const editing = useCohort((s) => s.editing)
  const setEditing = useCohort((s) => s.setEditing)
  const write = useCellWriter(pid)
  const target = info ? targetOf(info, caseId, scanIdx) : null
  if (!info || target === null || registry.readOnly) return <>{children}</>
  const send = (v: unknown) => {
    const cell: LabelCellIn = { column_id: info.col.column_id, target, value: v === '' ? null : v }
    void write(info.table.table_id, [cell], [{ ...cell, value: value ?? null }])
  }
  if (editing?.caseId === caseId && editing.scanIdx === scanIdx && editing.column === column.name)
    return (
      <CellEditor
        col={info.col}
        value={value}
        onCommit={(v) => {
          setEditing(null)
          if (String(v ?? '') !== String(value ?? '')) send(v)
        }}
        onCancel={() => setEditing(null)}
      />
    )
  return (
    <span
      className="cohort-editable"
      onClick={(e) => e.stopPropagation()}
      onDoubleClick={() => (info.col.type === 'bool' ? send(!value) : setEditing({ caseId, scanIdx, column: column.name }))}
    >
      {children}
    </span>
  )
}
