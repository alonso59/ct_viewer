// Phase / side consistency: the same case across two phases or sides, Bland–Altman style
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { fmtInt, fmtNum } from '../../../lib'
import type { ChartInstance } from '../Chart'
import { useRunDashboard } from '../store'
import { FeatureSelect, pickFeature, str, useFeatureNames, useFocusParams, usePid, ViewFrame, type ViewProps } from './common'
import { Scatter, type ScatterPoint } from './Scatter'

export function ConsistencyView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useRunDashboard(runId)
  const names = useFeatureNames(runId)
  const [wanted, setWanted] = useState<string | null>(null)
  const [kind, setKind] = useState<'phase' | 'side'>('phase')
  const [chart, setChart] = useState<ChartInstance | null>(null)
  const feature = pickFeature(names, wanted)
  useFocusParams(runId, 'phase-side-consistency', (p) => setWanted(str(p.feature) ?? wanted))
  const q = useDashboardView(pid, runId, 'phase-side-consistency', feature ? { filters, feature, pair: { kind } } : null)
  const d = q.data
  const points = useMemo<ScatterPoint[]>(
    () => (d?.points ?? []).map((p) => ({ item_id: p.item_id_a, case_id: p.case_id, x: p.mean, y: p.diff, level: null, note: `${p.item_id_b}` })),
    [d],
  )
  const lines = useMemo(
    () =>
      d && d.bias != null
        ? [
            { y: d.bias, label: t('dashboard.bias') },
            ...(d.loa_low != null ? [{ y: d.loa_low, label: t('dashboard.loa') }] : []),
            ...(d.loa_high != null ? [{ y: d.loa_high, label: t('dashboard.loa') }] : []),
          ]
        : [],
    [d, t],
  )
  const levelName = useMemo(() => () => '', [])
  return (
    <ViewFrame
      name={t('dashboard.view.phase-side-consistency')}
      query={q}
      chart={chart}
      csv={() => [['case_id', 'item_id_a', 'item_id_b', 'label', 'a', 'b', 'mean', 'diff'], ...(d?.points ?? []).map((p) => [p.case_id, p.item_id_a, p.item_id_b, p.label, p.a, p.b, p.mean, p.diff])]}
      controls={
        <>
          <FeatureSelect runId={runId} value={feature} onChange={setWanted} />
          <div className="seg" role="group" aria-label={t('dashboard.pair')}>
            {(['phase', 'side'] as const).map((k) => (
              <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>{t(`dashboard.pairKind.${k}`)}</button>
            ))}
          </div>
          {d ? (
            <span className="muted">
              {t('dashboard.pairSummary', { a: d.a, b: d.b, n: fmtInt(d.n_pairs), rho: d.rho != null ? fmtNum(d.rho) : '—' })}
            </span>
          ) : null}
        </>
      }
    >
      <Scatter runId={runId} points={points} xName={t('dashboard.meanAB')} yName={t('dashboard.diffAB', { a: d?.a ?? 'A', b: d?.b ?? 'B' })} levelName={levelName} markLines={lines} onReady={setChart} />
    </ViewFrame>
  )
}
