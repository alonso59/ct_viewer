// Correlation heat map: Spearman between features, clustered order; a cell opens the feature's distribution
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { NumberInput, fmtNum } from '../../../lib'
import { token } from '../../../theme'
import { Chart, fontSize, type ChartInstance, type ChartOption } from '../Chart'
import { useDashboardStore, useRunDashboard } from '../store'
import { numParam, usePid, useFocusParams, ViewFrame, type ViewProps } from './common'

export function CorrelationView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useRunDashboard(runId)
  const focusView = useDashboardStore((s) => s.focusView)
  const [threshold, setThreshold] = useState(0.9)
  const [chart, setChart] = useState<ChartInstance | null>(null)
  useFocusParams(runId, 'correlation', (p) => setThreshold(numParam(p.threshold) ?? threshold))
  const q = useDashboardView(pid, runId, 'correlation', { filters, threshold })
  const d = q.data
  const short = (f: string) => f.replace(/^original_/, '')
  const option = useMemo<ChartOption>(() => {
    if (!d) return {}
    const cells = d.matrix.flatMap((row, i) => row.map((v, j) => [j, i, v == null ? '-' : +v.toFixed(3)]))
    // Axis names only while they fit; the tooltip always names both features
    const labels = d.features.length <= 20
    return {
      grid: labels ? { left: 170, right: 70, top: 8, bottom: 130 } : { left: 16, right: 70, top: 8, bottom: 16 },
      tooltip: {
        formatter: (p: { data: [number, number, number | string] }) =>
          `${d.features[p.data[1]] ?? ''}<br/>${d.features[p.data[0]] ?? ''}<br/>ρ = ${typeof p.data[2] === 'number' ? fmtNum(p.data[2]) : '—'}`,
      },
      xAxis: { type: 'category', data: d.features.map(short), axisLabel: { show: labels, rotate: 70, fontSize: fontSize('--fs-badge') - 1, interval: 0 }, axisTick: { show: labels } },
      yAxis: { type: 'category', data: d.features.map(short), axisLabel: { show: labels, fontSize: fontSize('--fs-badge') - 1, interval: 0 }, axisTick: { show: labels } },
      visualMap: {
        min: -1, max: 1, calculable: true, orient: 'vertical', right: 0, top: 'center', itemHeight: 140,
        textStyle: { color: token('--fg-muted') }, inRange: { color: [token('--cat-1'), token('--bg-editor'), token('--cat-2')] },
      },
      series: [{ type: 'heatmap', data: cells, progressive: 4000 }],
    }
  }, [d])
  return (
    <ViewFrame
      name={t('dashboard.view.correlation')}
      query={q}
      chart={chart}
      csv={() => [['feature', ...(d?.features ?? [])], ...(d?.features ?? []).map((f, i) => [f, ...(d?.matrix[i] ?? [])])]}
      controls={
        <>
          <label className="db-inline">
            {t('dashboard.clusterThreshold')}
            <NumberInput className="input input-sm num" style={{ width: 64 }} step={0.05} min={0.5} max={1} value={threshold} onChange={(n) => setThreshold(Math.min(1, Math.max(0.5, n || 0.9)))} />
          </label>
          {d ? <span className="muted">{t('dashboard.clusters', { count: d.clusters.length, n: d.clusters.reduce((s, c) => s + c.features.length, 0) })}</span> : null}
          {d?.truncated ? <span className="badge" data-tone="warn">{t('dashboard.truncated')}</span> : null}
        </>
      }
    >
      <Chart
        option={option}
        onReady={setChart}
        onClick={(p) => {
          const f = d?.features[(p.data as number[] | undefined)?.[1] ?? -1]
          if (f) focusView(runId, 'feature-distribution', { feature: f })
        }}
      />
    </ViewFrame>
  )
}
