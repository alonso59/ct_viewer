// Group comparison: box + points per group for one feature, the chosen test (ANA-04) and the results
// table for all features (ANA-05); a result row switches the feature (DB-09).
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView, type ResultRow } from '../../../api'
import { fmtInt, fmtValue } from '../../../lib'
import { token } from '../../../theme'
import { Chart, type ChartInstance, type ChartOption } from '../Chart'
import { useRunDashboard } from '../store'
import {
  FeatureSelect,
  openRef,
  str,
  unitFor,
  useFocusParams,
  useItemMenu,
  useLevelColors,
  usePid,
  useSelection,
  VariableSelect,
  ViewFrame,
  type ItemRef,
  type ViewProps,
} from './common'
import { TestResult, ResultsTable, TestSwitch, type TestMode } from './stats'

/** Deterministic jitter in [-0.25, 0.25] from the item id */
function jitter(id: string): number {
  let h = 7
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0
  return ((Math.abs(h) % 1000) / 1000 - 0.5) * 0.5
}

interface Pt {
  value: [number, number]
  ref: ItemRef
  itemStyle: Record<string, unknown>
}

export function GroupComparisonView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useRunDashboard(runId)
  const [variable, setVariable] = useState<string | null>(null)
  const [feature, setFeature] = useState<string | null>(null)
  const [test, setTest] = useState<TestMode>('auto')
  const [chart, setChart] = useState<ChartInstance | null>(null)
  useFocusParams(runId, 'group-comparison', (p) => {
    setVariable(str(p.variable) ?? variable)
    setFeature(str(p.feature) ?? feature)
  })
  const q = useDashboardView(pid, runId, 'group-comparison', variable ? { filters, variable, feature, test, unit: unitFor(filters.label) } : null)
  const sel = useSelection(runId)
  const d = q.data
  const levels = useMemo(() => (d?.boxes ?? []).map((b) => b.level), [d])
  const color = useLevelColors(levels)
  const option = useMemo<ChartOption>(() => {
    if (!d) return {}
    const idx = new Map(levels.map((l, i) => [l, i]))
    const excluded = new Set(d.groups.filter((g) => g.excluded).map((g) => g.level))
    const pts: Pt[] = d.points.flatMap((p) => {
      const i = idx.get(p.group ?? null)
      if (i === undefined || p.value == null) return []
      return [{ value: [i + jitter(p.item_id), p.value], ref: { item_id: p.item_id, case_id: p.case_id }, itemStyle: sel.style(p.item_id, color(p.group)) }]
    })
    return {
      tooltip: {
        trigger: 'item',
        formatter: (p: { seriesType: string; data: Pt | number[]; name: string }) =>
          p.seriesType === 'scatter' ? `${(p.data as Pt).ref.item_id}<br/>${fmtValue((p.data as Pt).value[1])}` : p.name,
      },
      xAxis: [
        { type: 'category', data: levels.map((l) => (l !== null && excluded.has(l) ? t('dashboard.excludedLevel', { level: l ?? '' }) : (l ?? t('dashboard.missingLevel')))) },
        { type: 'value', min: -0.5, max: Math.max(levels.length - 0.5, 0.5), show: false },
      ],
      yAxis: { type: 'value', name: d.feature ?? '', scale: true },
      series: [
        {
          type: 'boxplot',
          xAxisIndex: 0,
          itemStyle: { color: 'transparent', borderColor: token('--fg-muted') },
          data: d.boxes.map((b) => [b.box.whisker_low, b.box.q1, b.box.median, b.box.q3, b.box.whisker_high].map((v) => v ?? 0)),
        },
        { type: 'scatter', xAxisIndex: 1, symbolSize: 7, data: pts },
      ],
    }
  }, [d, levels, color, sel, t])
  const onPoint = (p: { data?: unknown }) => openRef((p.data as Pt | undefined)?.ref)
  const pickRow = (r: ResultRow) => r.feature && setFeature(r.feature)
  return (
    <ViewFrame
      name={t('dashboard.view.group-comparison')}
      query={q}
      chart={chart}
      empty={variable ? null : t('dashboard.pickGrouping')}
      csv={() => [['feature', 'test', 'n', 'effect', 'effect_name', 'p', 'q'], ...(d?.results ?? []).map((r) => [r.feature, r.test, r.n, r.effect, r.effect_name, r.p, r.q])]}
      controls={
        <>
          <VariableSelect kind="categorical" value={variable} onChange={setVariable} label={t('dashboard.grouping')} />
          <FeatureSelect runId={runId} value={d?.feature ?? feature} onChange={setFeature} />
          <TestSwitch value={test} onChange={setTest} />
          {d ? <span className="muted">{t('dashboard.unitSummary', { rows: fmtInt(d.unit.n_rows), cases: fmtInt(d.unit.n_cases) })}</span> : null}
        </>
      }
    >
      {d ? (
        <div className="db-split">
          <div className="db-split-main db-stack">
            <TestResult choice={d.choice} row={d.selected} />
            <div className="db-chart-fill">
              <Chart
                option={option}
                onReady={setChart}
                onClick={onPoint}
                onContextMenu={(p, x, y) => {
                  const r = (p.data as Pt | undefined)?.ref
                  if (r && Array.isArray((p.data as Pt).value)) useItemMenu.getState().open(r, x, y)
                }}
              />
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
