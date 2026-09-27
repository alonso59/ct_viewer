// Outlier table: robust z (median/MAD) per item. An item is flagged when at least `min %` of its
// features are over the threshold (DB-10, owner 2026-09-27); flagged items are ranked by the number of
// features over the threshold, then by max |z| (AUD-A2-06); top 10 + "Show all"; one click opens the
// item (DB-03)
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView, useProject } from '../../../api'
import { ItemName, NumberInput, StatusBadge, featureUnit, fmtColumn, fmtInt } from '../../../lib'
import { useDashboardStore, useRunDashboard } from '../store'
import { asStatus, numParam, rowProps, useFocusParams, useLabelName, usePid, useSelection, ViewFrame, type ViewProps } from './common'

export const OUTLIERS_TOP = 10
export const OUTLIERS_THRESHOLD = 3.5
/** DB-10: share of an item's features that must be over the threshold, in % */
export const OUTLIERS_MIN_PCT = 5

export function OutliersView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useRunDashboard(runId)
  const focusView = useDashboardStore((s) => s.focusView)
  const modality = useProject(pid).data?.default_modality
  const [threshold, setThreshold] = useState(OUTLIERS_THRESHOLD)
  const [minPct, setMinPct] = useState(OUTLIERS_MIN_PCT)
  const [all, setAll] = useState(false)
  useFocusParams(runId, 'outliers', (p) => {
    setThreshold(numParam(p.threshold) ?? threshold)
    setMinPct(numParam(p.min_feature_pct) ?? minPct)
  })
  const body = { filters, threshold, min_feature_pct: minPct }
  const first = useDashboardView(pid, runId, 'outliers', { ...body, top_n: OUTLIERS_TOP })
  const nFlagged = first.data?.n_flagged ?? 0
  const more = all && nFlagged > OUTLIERS_TOP
  const full = useDashboardView(pid, runId, 'outliers', more ? { ...body, top_n: nFlagged } : null)
  const q = more && full.data ? full : first
  const labelName = useLabelName()
  const { selected } = useSelection(runId)
  const d = q.data
  // the server lists flagged items only (DB-10), ranked
  const rows = d?.items ?? []
  const zFmt = fmtColumn(rows.map((o) => o.max_abs_z))
  const vFmt = fmtColumn(rows.map((o) => o.top_features[0]?.value))
  return (
    <ViewFrame
      name={t('dashboard.view.outliers')}
      query={q}
      csv={() => [
        ['item_id', 'case_id', 'label', 'status', 'max_abs_z', 'n_outlier_features', 'top_feature', 'top_value', 'top_z'],
        ...rows.map((i) => [i.item_id, i.case_id, i.label, i.status, i.max_abs_z, i.n_outlier_features, i.top_features[0]?.feature, i.top_features[0]?.value, i.top_features[0]?.z]),
      ]}
      controls={
        <>
          <label className="db-inline">
            {t('dashboard.threshold')}
            <NumberInput className="input input-sm num" style={{ width: 64 }} step={0.5} min={1} value={threshold} onChange={(n) => setThreshold(n || OUTLIERS_THRESHOLD)} />
          </label>
          <label className="db-inline" title={t('dashboard.minPctHelp')}>
            {t('dashboard.minPct')}
            <NumberInput
              className="input input-sm num"
              style={{ width: 56 }}
              step={1}
              min={0}
              max={100}
              value={minPct}
              onChange={(n) => setMinPct(n == null ? OUTLIERS_MIN_PCT : Math.min(100, Math.max(0, n)))}
            />
          </label>
          {d ? (
            <span className="muted" title={t('dashboard.flaggedHelp', { threshold, pct: minPct, n: d.min_features, total: d.n_features })} data-testid="outliers-flagged">
              {t('dashboard.flagged', { n: fmtInt(d.n_flagged), total: fmtInt(d.n_items) })}
            </span>
          ) : null}
        </>
      }
    >
      {d && rows.length === 0 ? <div className="empty">{t('dashboard.noOutliers')}</div> : null}
      {rows.length ? (
        <>
          <table className="table db-outliers" aria-label={t('dashboard.view.outliers')}>
            <thead>
              <tr>
                <th>{t('dashboard.col.item')}</th>
                <th>{t('dashboard.label')}</th>
                <th className="num">{t('dashboard.col.nFeatures')}</th>
                <th className="num">{t('dashboard.col.maxZ')}</th>
                <th>{t('dashboard.col.topFeature')}</th>
                <th className="num">{t('dashboard.col.value')}</th>
                <th>{t('dashboard.filter.status')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => {
                const top = o.top_features[0]
                const unit = top ? featureUnit(top.feature, modality) : ''
                return (
                  <tr key={`${o.item_id}|${o.label}`} {...rowProps(o, selected, { label: t('dashboard.view.outliers'), rows })} title={t('dashboard.openInViewer')}>
                    <td className="truncate"><ItemName id={o.item_id} pid={pid} /></td>
                    <td>{labelName(o.label)}</td>
                    <td className="num">{fmtInt(o.n_outlier_features)}</td>
                    <td className="num" style={{ color: o.max_abs_z > threshold * 2 ? 'var(--error)' : 'var(--warn)' }}>{zFmt(o.max_abs_z)}</td>
                    <td className="mono db-top-feature">
                      {top ? (
                        <button
                          type="button"
                          className="link truncate"
                          title={top.feature}
                          onClick={(e) => {
                            e.stopPropagation()
                            focusView(runId, 'feature-distribution', { feature: top.feature })
                          }}
                        >
                          {top.feature}
                        </button>
                      ) : null}
                    </td>
                    <td className="num">
                      {vFmt(top?.value)}
                      {unit && top?.value != null ? <span className="muted"> {unit}</span> : null}
                    </td>
                    <td><StatusBadge status={asStatus(o.status)} compact /></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {nFlagged > OUTLIERS_TOP ? (
            <div className="db-more">
              <button type="button" className="btn btn-sm" aria-expanded={all} onClick={() => setAll(!all)}>
                {all ? t('dashboard.showTop', { n: OUTLIERS_TOP }) : t('dashboard.showAll', { n: fmtInt(nFlagged) })}
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </ViewFrame>
  )
}
