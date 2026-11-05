import type { UseQueryResult } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { CohortSummary } from '../../api'
import { token } from '../../theme'
import { Chart, axisStyle, type ChartInstance, type ChartOption } from './Chart'
import { ChartOrTable, ViewFrame, type CsvRows } from './views/common'

interface Bar {
  label: string
  count: number
  /** The filter a click adds; none for the Other and Missing bars */
  value: string | null
}

const barsOf = (s: CohortSummary, other: string, missing: string): Bar[] => {
  const bars: Bar[] = s.bins
    ? s.bins.map((b) => ({ label: `${b.lo}..${b.hi}`, count: b.count, value: `${b.lo}..${b.hi}` }))
    : Object.entries(s.counts ?? {}).map(([label, count]) => ({ label, count, value: label }))
  if (s.other) bars.push({ label: other, count: s.other, value: null })
  if (s.missing) bars.push({ label: missing, count: s.missing, value: null })
  return bars
}

/** One column's distribution (bars, or a histogram for numbers and dates) with its table and exports;
 *  a click on a bar or bin calls `onPick` with the filter value it stands for */
export function ValueSummary({ name, summary, query, onPick }: {
  name: string
  summary: CohortSummary | undefined
  query: Pick<UseQueryResult<unknown>, 'isLoading' | 'error' | 'data' | 'isFetching'>
  onPick: (value: string) => void
}) {
  const { t } = useTranslation()
  const [chart, setChart] = useState<ChartInstance | null>(null)
  const bars = useMemo(() => (summary ? barsOf(summary, t('cohort.summary.other'), t('cohort.summary.missing')) : []), [summary, t])
  const option = useMemo<ChartOption>(() => ({
    grid: { left: 48, right: 16, top: 16, bottom: 64 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: bars.map((b) => b.label), ...axisStyle(), axisLabel: { ...axisStyle().axisLabel, rotate: 30, interval: 0 } },
    yAxis: { type: 'value', minInterval: 1, ...axisStyle() },
    series: [{ type: 'bar', data: bars.map((b) => b.count), itemStyle: { color: token('--accent') }, barCategoryGap: summary?.bins ? '5%' : '30%' }],
  }), [bars, summary?.bins])
  const rows = (): CsvRows => [[t('cohort.summary.value'), t('cohort.summary.count')], ...bars.map((b) => [b.label, b.count])]
  return (
    <ViewFrame name={`summary-${name}`} chart={bars.length ? chart : undefined} csv={rows} query={query} empty={summary && bars.length === 0 ? t('cohort.summary.none') : null}>
      <ChartOrTable rows={rows}>
        <Chart
          option={option}
          height={220}
          onReady={setChart}
          onClick={(p) => {
            const value = bars[p.dataIndex]?.value
            if (value) onPick(value)
          }}
        />
      </ChartOrTable>
    </ViewFrame>
  )
}
