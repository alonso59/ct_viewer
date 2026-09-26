// Outlier table: robust z (median/MAD) per item, top-N items and features; one click opens the item
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { StatusBadge, fmt1, fmtInt, fmtNum } from '../../../lib'
import { useDashboardStore, useRunDashboard } from '../store'
import { asStatus, numParam, rowProps, useFocusParams, useLabelName, usePid, useSelection, ViewFrame, type ViewProps } from './common'

export function OutliersView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useRunDashboard(runId)
  const focusView = useDashboardStore((s) => s.focusView)
  const [threshold, setThreshold] = useState(3.5)
  useFocusParams(runId, 'outliers', (p) => setThreshold(numParam(p.threshold) ?? threshold))
  const q = useDashboardView(pid, runId, 'outliers', { filters, threshold })
  const labelName = useLabelName()
  const { selected } = useSelection(runId)
  const d = q.data
  const zFmt = (z: number) => (Math.abs(z) >= 1e4 ? z.toExponential(1) : fmt1(z))
  return (
    <ViewFrame
      name={t('dashboard.view.outliers')}
      query={q}
      csv={() => [
        ['item_id', 'case_id', 'label', 'status', 'max_abs_z', 'n_outlier_features', 'top_feature', 'top_value', 'top_z'],
        ...(d?.items ?? []).map((i) => [i.item_id, i.case_id, i.label, i.status, i.max_abs_z, i.n_outlier_features, i.top_features[0]?.feature, i.top_features[0]?.value, i.top_features[0]?.z]),
      ]}
      controls={
        <>
          <label className="db-inline">
            {t('dashboard.threshold')}
            <input className="input input-sm num" style={{ width: 64 }} type="number" step={0.5} min={1} value={threshold} onChange={(e) => setThreshold(+e.target.value || 3.5)} />
          </label>
          {d ? <span className="muted">{t('dashboard.flagged', { n: fmtInt(d.n_flagged), total: fmtInt(d.n_items) })}</span> : null}
        </>
      }
    >
      {d && d.items.length === 0 ? <div className="empty">{t('dashboard.noOutliers')}</div> : null}
      {d?.items.length ? (
        <table className="table" aria-label={t('dashboard.view.outliers')}>
          <thead>
            <tr>
              <th>{t('dashboard.col.item')}</th>
              <th>{t('dashboard.label')}</th>
              <th className="num">{t('dashboard.col.maxZ')}</th>
              <th className="num">{t('dashboard.col.nFeatures')}</th>
              <th>{t('dashboard.col.topFeature')}</th>
              <th className="num">{t('dashboard.col.value')}</th>
              <th>{t('dashboard.filter.status')}</th>
            </tr>
          </thead>
          <tbody>
            {d.items.map((o) => {
              const top = o.top_features[0]
              return (
                <tr key={`${o.item_id}|${o.label}`} {...rowProps(o, selected, { label: t('dashboard.view.outliers'), rows: d.items })} title={t('dashboard.openInViewer')}>
                  <td className="mono">{o.item_id}</td>
                  <td>{labelName(o.label)}</td>
                  <td className="num" style={{ color: o.max_abs_z > threshold * 2 ? 'var(--error)' : 'var(--warn)' }}>{zFmt(o.max_abs_z)}</td>
                  <td className="num">{fmtInt(o.n_outlier_features)}</td>
                  <td className="mono">
                    {top ? (
                      <button
                        type="button"
                        className="link"
                        onClick={(e) => {
                          e.stopPropagation()
                          focusView(runId, 'feature-distribution', { feature: top.feature })
                        }}
                      >
                        {top.feature}
                      </button>
                    ) : null}
                  </td>
                  <td className="num">{top?.value != null ? fmtNum(top.value) : '—'}</td>
                  <td><StatusBadge status={asStatus(o.status)} compact /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : null}
    </ViewFrame>
  )
}
