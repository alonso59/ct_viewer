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
      csv={() => [['item_id', 'label', 'kind', 'code', 'message', 'detail'], ...(d?.errors ?? []).map((e) => [e.item_id, e.label, e.kind, e.code, e.message, e.detail])]}
    >
      {d ? (
        <div className="db-overview">
          <div className="kpis">
            <div><span className="kpi num">{fmtInt(d.n_items_selected)}</span><span className="muted">{t('dashboard.kpi.items')}</span></div>
            <div><span className="kpi num" style={{ color: 'var(--ok)' }}>{fmtInt(d.n_items_ok)}</span><span className="muted">{t('dashboard.kpi.ok')}</span></div>
            <div><span className="kpi num" style={{ color: d.n_items_failed ? 'var(--error)' : undefined }}>{fmtInt(d.n_items_failed)}</span><span className="muted">{t('dashboard.kpi.failed')}</span></div>
            {/* TSK-04 (AUD-A2-05): items known not ready are skipped, never failed */}
            <div title={t('dashboard.kpi.skippedHelp')}><span className="kpi num" style={{ color: d.n_items_skipped ? 'var(--warn)' : undefined }}>{fmtInt(d.n_items_skipped ?? 0)}</span><span className="muted">{t('dashboard.kpi.skipped')}</span></div>
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
          {d.phase_changed?.length ? (
            // PHS-03 (AUD-A5-04): views use the effective phase; the run's value is kept as "phase at run time"
            <details className="db-phase-changed">
              <summary className="muted">{t('dashboard.phaseChanged', { count: d.phase_changed.length })}</summary>
              <ul>
                {d.phase_changed.map((c) => (
                  <li key={c.item_id} className="mono">{t('dashboard.phaseAtRun', { item: c.item_id, phase: c.phase, atRun: c.phase_at_run })}</li>
                ))}
              </ul>
            </details>
          ) : null}
          {d.errors.length ? (
            <>
              <div className="section-title">{t('dashboard.errors', { count: d.n_errors })}</div>
              <table className="table" aria-label={t('dashboard.errorsTable')}>
                <tbody>
                  {d.errors.map((e, i) => {
                    const skipped = e.kind === 'skipped'
                    const icon = (
                      <td style={{ color: skipped ? 'var(--warn)' : 'var(--error)', width: 20 }} title={t(`rad.errKindName.${skipped ? 'skipped' : 'failed'}`)}>
                        <Icon spec={codicon(skipped ? 'debug-step-over' : 'error')} />
                      </td>
                    )
                    return e.item_id ? (
                      <tr key={`${e.item_id}|${e.label ?? ''}|${i}`} data-kind={e.kind} {...rowProps({ item_id: e.item_id, case_id: e.case_id ?? e.item_id.split('.')[0] ?? '' }, selected)} title={t('dashboard.openInViewer')}>
                        {icon}
                        <td className="mono">{e.item_id}</td>
                        <td>{e.label != null ? labelName(e.label) : ''}</td>
                        <td>{t(`rad.errKindName.${skipped ? 'skipped' : 'failed'}`)}</td>
                        <td className="muted" style={{ whiteSpace: 'normal' }} title={e.detail ?? undefined}>{e.message}</td>
                      </tr>
                    ) : (
                      <tr key={i}>{icon}<td colSpan={4} className="muted">{e.message}</td></tr>
                    )
                  })}
                </tbody>
              </table>
            </>
          ) : null}
        </div>
      ) : null}
    </ViewFrame>
  )
}
