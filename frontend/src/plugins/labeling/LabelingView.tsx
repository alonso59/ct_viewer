// Labeling view (LBL-01/08): the project's label tables with fill progress; New table.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useLabelTables, useProject, type LabelTableInfo } from '../../api'
import { ProblemCard, Progress } from '../../lib'
import { openEditor, registry, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { NewTableDialog } from './NewTableDialog'
import './labeling.css'

function TableCard({ t }: { t: LabelTableInfo }) {
  const { t: tr } = useTranslation()
  const cols = (t.columns ?? []).filter((c) => !c.hidden)
  const filled = (t.progress ?? []).reduce((n, p) => n + p.filled, 0)
  const total = t.n_rows * cols.length
  return (
    <li>
      <button type="button" className="lbl-card" onClick={() => openEditor('labeling', { tableId: t.table_id })}>
        <span className="lbl-card-head">
          <Icon spec={codicon('table')} />
          <strong>{t.name}</strong>
          <span className="badge">{tr(`lbl.level.${t.level}`)}</span>
        </span>
        <span className="muted lbl-small">{tr('lbl.summary', { rows: t.n_rows, cols: cols.length, filled, total })}</span>
        <Progress value={filled} total={total || 1} />
        <span className="lbl-cols">
          {cols.map((c) => {
            const p = t.progress?.find((x) => x.column_id === c.column_id)?.filled ?? 0
            return (
              <span key={c.column_id} className="lbl-small muted" title={c.description ?? ''}>
                {tr('lbl.colProgress', { name: c.name, filled: p, total: t.n_rows })}
              </span>
            )
          })}
        </span>
      </button>
    </li>
  )
}

export default function LabelingView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const tables = useLabelTables(pid)
  const labels = useProject(pid).data?.label_map ?? []
  const [creating, setCreating] = useState(false)
  return (
    <div className="lbl-view">
      {registry.readOnly ? null : (
        <button type="button" className="btn btn-sm" onClick={() => setCreating(true)}>
          <Icon spec={codicon('add')} />
          {t('lbl.newTable')}
        </button>
      )}
      {tables.error ? <ProblemCard error={tables.error} /> : null}
      {tables.data && !tables.data.length ? <p className="muted">{t('lbl.empty')}</p> : null}
      <ul className="lbl-list">{(tables.data ?? []).map((x) => <TableCard key={x.table_id} t={x} />)}</ul>
      {creating ? <NewTableDialog pid={pid} labels={labels.map((l) => l.name)} onClose={() => setCreating(false)} /> : null}
    </div>
  )
}
