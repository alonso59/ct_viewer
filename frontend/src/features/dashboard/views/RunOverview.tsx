// Run overview: items ok/failed, per-label and per-phase counts, curation, runtime, errors → item
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { StatusBadge, fmtDuration, fmtInt } from '../../../lib'
import { Icon, codicon } from '../../../theme'
import { useRunDashboard } from '../store'
import { asStatus, rowProps, useLabelName, usePid, useSelection, ViewFrame, type ViewProps } from './common'

export function RunOverviewView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useRunDashboard(runId)
  const q = useDashboardView(pid, runId, 'run-overview', { filters })
  const labelName = useLabelName()
  const { selected } = useSelection(runId)
  const d = q.data
  return (
    <ViewFrame
      name={t('dashboard.view.run-overview')}
      query={q}
      csv={() => [['item_id', 'label', 'message'], ...(d?.errors ?? []).map((e) => [e.item_id, e.label, e.message])]}
    >
      {d ? (
        <div className="db-overview">
          <div className="kpis">
            <div><span className="kpi num">{fmtInt(d.n_items_selected)}</span><span className="muted">{t('dashboard.kpi.items')}</span></div>
            <div><span className="kpi num" style={{ color: 'var(--ok)' }}>{fmtInt(d.n_items_ok)}</span><span className="muted">{t('dashboard.kpi.ok')}</span></div>
            <div><span className="kpi num" style={{ color: d.n_items_failed ? 'var(--error)' : undefined }}>{fmtInt(d.n_items_failed)}</span><span className="muted">{t('dashboard.kpi.failed')}</span></div>
            <div><span className="kpi num">{fmtInt(d.n_features)}</span><span className="muted">{t('dashboard.kpi.features')}</span></div>
            <div><span className="kpi num">{d.runtime_s != null ? fmtDuration(d.runtime_s) : '—'}</span><span className="muted">{t('dashboard.kpi.runtime')}</span></div>
          </div>
          <div className="db-overview-lists">
            <table className="table">
              <thead><tr><th>{t('dashboard.label')}</th><th className="num">{t('dashboard.kpi.items')}</th></tr></thead>
              <tbody>
                {d.per_label.map((l) => (
                  <tr key={l.label}><td>{labelName(l.label)}</td><td className="num">{fmtInt(l.n_items)}</td></tr>
                ))}
              </tbody>
            </table>
            <table className="table">
              <thead><tr><th>{t('dashboard.filter.phase')}</th><th className="num">{t('dashboard.kpi.items')}</th></tr></thead>
              <tbody>
                {d.per_phase.map((l) => (
                  <tr key={l.level}><td className="mono">{l.level}</td><td className="num">{fmtInt(l.n)}</td></tr>
                ))}
              </tbody>
            </table>
            <table className="table">
              <thead><tr><th>{t('dashboard.filter.status')}</th><th className="num">{t('dashboard.kpi.items')}</th></tr></thead>
              <tbody>
                {d.curation.map((l) => (
                  <tr key={l.level}><td><StatusBadge status={asStatus(l.level)} /></td><td className="num">{fmtInt(l.n)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.errors.length ? (
            <>
              <div className="section-title">{t('dashboard.errors', { count: d.n_errors })}</div>
              <table className="table">
                <tbody>
                  {d.errors.map((e, i) =>
                    e.item_id ? (
                      <tr key={`${e.item_id}|${e.label ?? ''}|${i}`} {...rowProps({ item_id: e.item_id, case_id: e.case_id ?? e.item_id.split('.')[0] ?? '' }, selected)} title={t('dashboard.openInViewer')}>
                        <td style={{ color: 'var(--error)', width: 20 }}><Icon spec={codicon('error')} /></td>
                        <td className="mono">{e.item_id}</td>
                        <td>{e.label != null ? labelName(e.label) : ''}</td>
                        <td className="muted" style={{ whiteSpace: 'normal' }}>{e.message}</td>
                      </tr>
                    ) : (
                      <tr key={i}><td /><td colSpan={3} className="muted">{e.message}</td></tr>
                    ),
                  )}
                </tbody>
              </table>
            </>
          ) : null}
        </div>
      ) : null}
    </ViewFrame>
  )
}
