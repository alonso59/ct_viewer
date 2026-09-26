// Left pane Dashboards view: completed runs → dashboard tab
import { useTranslation } from 'react-i18next'

import { useRuns } from '../../api'
import { fmtAgo } from '../../lib'
import { openEditor, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'

export function DashboardsView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const runs = (useRuns(pid).data ?? []).filter((r) => r.status === 'completed' || r.status === 'completed_with_errors')
  // AUD-A1-10: the empty state starts a run (the Radiomics settings tab, UI-20)
  if (!runs.length)
    return (
      <div className="empty">
        <p>{t('dashboard.noRuns')}</p>
        <button type="button" className="btn btn-primary" onClick={() => openEditor('radiomics', {})}>
          <Icon spec={codicon('beaker')} />
          {t('radiomics.newRun')}
        </button>
      </div>
    )
  return (
    <div>
      {runs.map((r) => (
        <button key={r.run_id} type="button" className="list-row" style={{ minHeight: 40, flexDirection: 'column', alignItems: 'stretch', gap: 2, padding: '4px 12px' }} onClick={() => openEditor('run', { runId: r.run_id })}>
          <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <Icon spec={codicon('graph')} />
            {r.name}
          </span>
          <span className="muted" style={{ fontSize: 'var(--fs-badge)' }}>
            {t('radiomics.runMeta', { items: r.counts.items, features: r.counts.features, ago: fmtAgo(r.created_at) })}
          </span>
        </button>
      ))}
    </div>
  )
}
