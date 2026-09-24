// Feature distribution: histogram split by the colour variable (DB-07); a bar selects its items (DB-04)
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { fmtNum } from '../../../lib'
import { Chart, type ChartInstance, type ChartOption } from '../Chart'
import { useRunDashboard } from '../store'
import {
  FeatureSelect,
  openRef,
  pickFeature,
  str,
  useFeatureNames,
  useFocusParams,
  useLevelColors,
  useLevelName,
  usePid,
  useSelection,
  ViewFrame,
  type ViewProps,
} from './common'

export function DistributionView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters, colorBy } = useRunDashboard(runId)
  const names = useFeatureNames(runId)
  const [wanted, setWanted] = useState<string | null>(null)
  const [log, setLog] = useState(false)
  const [chart, setChart] = useState<ChartInstance | null>(null)
  const feature = pickFeature(names, wanted)
  useFocusParams(runId, 'feature-distribution', (p) => setWanted(str(p.feature) ?? wanted))
  const q = useDashboardView(pid, runId, 'feature-distribution', feature ? { filters, feature, split: colorBy, log_scale: log } : null)
  const sel = useSelection(runId)
  const levelName = useLevelName(colorBy)
  const d = q.data
  const levels = useMemo(() => (d?.groups ?? []).map((g) => g.level), [d])
  const color = useLevelColors(levels)
  const option = useMemo<ChartOption>(() => {
    if (!d) return {}
    const selectedBins = new Set(d.points.filter((p) => sel.selected.has(p.item_id)).map((p) => `${p.color ?? ''}|${p.bin ?? -1}`))
    return {
      legend: levels.length > 1 ? { data: levels.map(levelName) } : { show: false },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'category', data: d.edges.slice(0, -1).map((e) => fmtNum(e)), name: d.log_scale ? t('dashboard.log10', { name: d.feature }) : d.feature, nameLocation: 'middle', nameGap: 26 },
      yAxis: { type: 'value', name: t('dashboard.count'), minInterval: 1 },
      series: d.groups.map((g) => ({
        name: levelName(g.level),
        type: 'bar',
        stack: 'h',
        barCategoryGap: '8%',
        itemStyle: { color: color(g.level) },
        data: g.counts.map((n, bin) => ({
          value: n,
          itemStyle: sel.any ? { opacity: selectedBins.has(`${g.level ?? ''}|${bin}`) ? 1 : 0.3 } : undefined,
        })),
      })),
    }
  }, [d, levels, levelName, color, sel, t])
  const onBar = (p: { dataIndex: number; seriesIndex?: number }) => {
    const level = d?.groups[p.seriesIndex ?? 0]?.level ?? null
    const pts = (d?.points ?? []).filter((x) => x.bin === p.dataIndex && (x.color ?? null) === level)
    if (pts.length === 1) openRef(pts[0])
    else sel.select(pts.map((x) => x.item_id))
  }
  return (
    <ViewFrame
      name={t('dashboard.view.feature-distribution')}
      query={q}
      chart={chart}
      csv={() => [['item_id', 'case_id', 'label', 'split', feature ?? ''], ...(d?.points ?? []).map((p) => [p.item_id, p.case_id, p.label, p.color, p.value])]}
      controls={
        <>
          <FeatureSelect runId={runId} value={feature} onChange={setWanted} />
          <label className="check">
            <input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} />
            {t('dashboard.logScale')}
          </label>
        </>
      }
    >
      <Chart option={option} onReady={setChart} onClick={onBar} />
    </ViewFrame>
  )
}
