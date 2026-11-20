// Paired consistency: the same case across two phases or sides, or the same item across two
// labels (e.g. tumor core vs rim), Bland–Altman style, with a paired test of every feature
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView, useTable, type ResultRow } from '../../../api'
import { fmtInt, fmtNum } from '../../../lib'
import type { ChartInstance } from '../Chart'
import { useTableDashboard } from '../store'
import { FeatureSelect, pickFeature, str, useFeatureNames, useFocusParams, useLabelName, usePid, ViewFrame, type ViewProps } from './common'
import { Scatter, type ScatterPoint } from './Scatter'
import { ResultsTable, TestResult, TestSwitch, type TestMode } from './stats'

type PairKind = 'phase' | 'side' | 'label'

export function ConsistencyView({ tableId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useTableDashboard(tableId)
  const names = useFeatureNames(tableId)
  const tableLabels = useTable(pid, tableId).data?.labels ?? []
  const labelName = useLabelName()
  const [wanted, setWanted] = useState<string | null>(null)
  const [kind, setKind] = useState<PairKind>('phase')
  const [pairA, setPairA] = useState<string | null>(null)
  const [pairB, setPairB] = useState<string | null>(null)
  const [test, setTest] = useState<TestMode>('auto')
  const [chart, setChart] = useState<ChartInstance | null>(null)
  const feature = pickFeature(names, wanted)
  useFocusParams(tableId, 'phase-side-consistency', (p) => setWanted(str(p.feature) ?? wanted))
  const pair = kind === 'label' ? { kind, a: pairA ?? undefined, b: pairB ?? undefined } : { kind }
  const q = useDashboardView(pid, tableId, 'phase-side-consistency', feature ? { filters, feature, pair, test } : null)
  const d = q.data
  const points = useMemo<ScatterPoint[]>(
    () => (d?.points ?? []).map((p) => ({ item_id: p.item_id_a, case_id: p.case_id, x: p.mean, y: p.diff, level: null, note: p.item_id_b })),
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
  const end = (v: string | undefined) => (d?.kind === 'label' && v ? labelName(Number(v)) : (v ?? ''))
  const labelSelect = (value: string | null, onChange: (v: string) => void, aria: string, fallback: string | undefined) => (
    <select className="select" aria-label={aria} value={value ?? fallback ?? ''} onChange={(e) => onChange(e.target.value)}>
      {tableLabels.map((l) => <option key={l} value={String(l)}>{labelName(l)}</option>)}
    </select>
  )
  const pickRow = (r: ResultRow) => r.feature && setWanted(r.feature)
  return (
    <ViewFrame
      name={t('dashboard.view.phase-side-consistency')}
      query={q}
      chart={chart}
      csv={() => [['case_id', 'item_id_a', 'item_id_b', 'label', 'a', 'b', 'mean', 'diff'], ...(d?.points ?? []).map((p) => [p.case_id, p.item_id_a, p.item_id_b, p.label, p.a, p.b, p.mean, p.diff])]}
      controls={
        <>
          <FeatureSelect tableId={tableId} value={feature} onChange={setWanted} />
          <div className="seg" role="group" aria-label={t('dashboard.pair')}>
            {(['phase', 'side', 'label'] as const).map((k) => (
              <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>{t(`dashboard.pairKind.${k}`)}</button>
            ))}
          </div>
          {kind === 'label' ? (
            <>
              {labelSelect(pairA, setPairA, t('dashboard.pairA'), d?.a)}
              {labelSelect(pairB, setPairB, t('dashboard.pairB'), d?.b)}
            </>
          ) : null}
          <TestSwitch value={test} onChange={setTest} />
          {d ? (
            <span className="muted">
              {t('dashboard.pairSummary', { a: end(d.a), b: end(d.b), n: fmtInt(d.n_pairs), rho: d.rho != null ? fmtNum(d.rho) : '—' })}
            </span>
          ) : null}
        </>
      }
    >
      {d ? (
        <div className="db-split">
          <div className="db-split-main db-stack">
            <TestResult row={d.selected} />
            <div className="db-chart-fill">
              <Scatter tableId={tableId} points={points} xName={t('dashboard.meanAB')} yName={t('dashboard.diffAB', { a: end(d.b), b: end(d.a) })} levelName={levelName} markLines={lines} onReady={setChart} />
            </div>
          </div>
          <div className="db-split-side">
            <ResultsTable rows={d.results} selected={d.feature} onPick={pickRow} />
          </div>
        </div>
      ) : null}
    </ViewFrame>
  )
}
