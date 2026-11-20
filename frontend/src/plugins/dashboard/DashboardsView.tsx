// Left pane Dashboards view: finished analysis tables by kind (radiomics runs, VOI lesions, …) → dashboard tab
import { useTranslation } from 'react-i18next'

import { useTables, type RunStatus, type TableSummary } from '../../api'
import { fmtAgo } from '../../lib'
import { openEditor, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'

const DONE: string[] = ['completed', 'completed_with_errors'] satisfies RunStatus[]
const KNOWN_KINDS = new Set(['radiomics', 'voi_lesions'])

function TableRow({ table }: { table: TableSummary }) {
  const { t } = useTranslation()
  const counts = table.counts ?? { items: 0, columns: 0 }
  const ago = fmtAgo(table.created_at)
  const meta =
    table.grain === 'instance'
      ? t('dashboard.instanceMeta', { count: counts.observations ?? 0, name: table.instance_name ?? '', items: counts.items, columns: counts.columns, ago })
      : t('dashboard.tableMeta', { items: counts.items, columns: counts.columns, ago })
  return (
    <button type="button" className="list-row" style={{ minHeight: 40, flexDirection: 'column', alignItems: 'stretch', gap: 2, padding: '4px 12px' }} onClick={() => openEditor('table', { tableId: table.table_id })}>
      <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <Icon spec={codicon('graph')} />
        {table.title}
      </span>
      <span className="muted" style={{ fontSize: 'var(--fs-badge)' }}>
        {meta}
      </span>
    </button>
  )
}

export function DashboardsView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const tables = (useTables(pid).data ?? []).filter((r) => DONE.includes(r.status))
  if (!tables.length)
    return (
      <div className="empty">
        <p>{t('dashboard.noRuns')}</p>
        <button type="button" className="btn btn-primary" onClick={() => openEditor('radiomics', {})}>
          <Icon spec={codicon('beaker')} />
          {t('radiomics.newRun')}
        </button>
      </div>
    )
  const kinds = [...new Set(tables.map((r) => r.kind))]
  return (
    <div>
      {kinds.map((kind) => (
        <section key={kind} aria-label={KNOWN_KINDS.has(kind) ? t(`dashboard.kind.${kind}`) : kind}>
          {kinds.length > 1 ? <div className="section-title muted" style={{ padding: '6px 12px 2px' }}>{KNOWN_KINDS.has(kind) ? t(`dashboard.kind.${kind}`) : kind}</div> : null}
          {tables
            .filter((r) => r.kind === kind)
            .map((r) => (
              <TableRow key={r.table_id} table={r} />
            ))}
        </section>
      ))}
    </div>
  )
}
