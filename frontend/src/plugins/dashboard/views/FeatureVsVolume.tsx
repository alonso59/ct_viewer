// Feature vs volume: scatter against mesh volume (flags size-driven features) + ranked table by |ρ|
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { fmtInt, fmtNum, useRowKeys } from '../../../lib'
import type { ChartInstance } from '../Chart'
import { useTableDashboard } from '../store'
import {
  asStatus,
  FeatureSelect,
  pickFeature,
  str,
  useFeatureNames,
  useFocusParams,
  useLevelName,
  usePid,
  ValueFlag,
  ViewFrame,
  type ViewProps,
} from './common'
import { Scatter, type ScatterPoint } from './Scatter'

export function FeatureVsVolumeView({ tableId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters, colorBy } = useTableDashboard(tableId)
  const names = useFeatureNames(tableId)
  const [wanted, setWanted] = useState<string | null>(null)
  const [chart, setChart] = useState<ChartInstance | null>(null)
  const feature = pickFeature(names.filter((n) => !n.name.endsWith('_MeshVolume')), wanted)
  useFocusParams(tableId, 'feature-vs-volume', (p) => setWanted(str(p.feature) ?? wanted))
  const q = useDashboardView(pid, tableId, 'feature-vs-volume', feature ? { filters, feature, color_by: colorBy } : null)
  const levelName = useLevelName(colorBy)
  const d = q.data
  const points = useMemo<ScatterPoint[]>(
    () => (d?.points ?? []).map((p) => ({ item_id: p.item_id, case_id: p.case_id, x: p.x, y: p.y, level: p.color ?? null, note: t(`status.${asStatus(p.status)}`) })),
    [d, t],
  )
  const rowKeys = useRowKeys((d?.ranked ?? []).map((r) => r.feature))
  return (
    <ViewFrame
      name={t('dashboard.view.feature-vs-volume')}
      query={q}
      chart={chart}
      csv={() => [['item_id', 'case_id', 'label', 'color', d?.volume_feature ?? 'volume', feature ?? ''], ...(d?.points ?? []).map((p) => [p.item_id, p.case_id, p.label, p.color, p.x, p.y])]}
      controls={
        <>
          <FeatureSelect tableId={tableId} value={feature} onChange={setWanted} exclude={d?.volume_feature} />
          {d ? <span className="muted">{t('dashboard.rho', { rho: d.rho != null ? fmtNum(d.rho) : '—', n: fmtInt(d.n) })}</span> : null}
          {d?.size_driven ? <span className="badge" data-tone="warn">{t('dashboard.sizeDriven')}</span> : null}
        </>
      }
    >
      <div className="db-split">
        <div className="db-split-main">
          <Scatter tableId={tableId} points={points} xName={d?.volume_feature ?? ''} yName={feature ?? ''} levelName={levelName} onReady={setChart} />
        </div>
        <div className="db-split-side">
          <table className="table">
            <thead>
              <tr><th>{t('dashboard.feature')}</th><th className="num">{t('dashboard.col.rho')}</th></tr>
            </thead>
            <tbody>
              {(d?.ranked ?? []).map((r) => (
                <tr key={r.feature} data-clickable="true" aria-selected={r.feature === feature || undefined} onClick={() => setWanted(r.feature)} {...rowKeys(r.feature)}>
                  <td className="mono">{r.feature.replace(/^original_/, '')}</td>
                  <td className="num" style={{ color: Math.abs(r.rho ?? 0) > 0.8 ? 'var(--warn)' : undefined }}>
                    {r.rho != null ? fmtNum(r.rho) : '—'}
                    {Math.abs(r.rho ?? 0) > 0.8 ? <ValueFlag tone="warn" icon="warning" label={t('dashboard.flag.followsVolume')} /> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </ViewFrame>
  )
}
