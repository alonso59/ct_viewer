import type { UseQueryResult } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { CohortBalance } from '../../api'
import { fmtValue } from '../../lib'
import { token } from '../../theme'
import { Chart, axisStyle, fontSize, type ChartInstance, type ChartOption } from './Chart'
import { ChartOrTable, ViewFrame, type CsvRows } from './views/common'

/** Counts of one categorical variable by another as a heat map, with the test that compares them */
export function ContingencyMap({ name, balance, query }: {
  name: string
  balance: CohortBalance | undefined
  query: Pick<UseQueryResult<unknown>, 'isLoading' | 'error' | 'data' | 'isFetching'>
}) {
  const { t } = useTranslation()
  const [chart, setChart] = useState<ChartInstance | null>(null)
  const rows = useMemo(() => balance?.rows ?? [], [balance])
  const cols = useMemo(() => balance?.cols ?? [], [balance])
  const counts = useMemo(() => new Map((balance?.cells ?? []).map((c) => [`${c.row}\u0000${c.col}`, c.n])), [balance])
  const option = useMemo<ChartOption>(() => {
    const max = Math.max(1, ...counts.values())
    return {
      grid: { left: 96, right: 24, top: 8, bottom: 56 },
      tooltip: { position: 'top' },
      xAxis: { type: 'category', data: cols, splitArea: { show: true }, ...axisStyle() },
      yAxis: { type: 'category', data: rows, splitArea: { show: true }, ...axisStyle() },
      visualMap: { min: 0, max, show: false, inRange: { color: [token('--bg-panel'), token('--accent')] } },
      series: [{
        type: 'heatmap',
        data: rows.flatMap((r, y) => cols.map((c, x) => [x, y, counts.get(`${r}\u0000${c}`) ?? 0])),
        label: { show: true, color: token('--fg'), fontSize: fontSize('--fs-panel') },
      }],
    }
  }, [rows, cols, counts])
  const table = (): CsvRows => [[name, ...cols], ...rows.map((r) => [r, ...cols.map((c) => counts.get(`${r}\u0000${c}`) ?? 0)])]
  const test = balance?.test
  const excluded = [...(balance?.excluded_rows ?? []), ...(balance?.excluded_cols ?? [])]
  const empty = balance && (rows.length < 2 || cols.length < 2) ? t('cohort.balance.tooFew') : null
  return (
    <ViewFrame name={`balance-${name}`} chart={rows.length ? chart : undefined} csv={table} query={query} empty={empty}>
      <ChartOrTable rows={table}>
        <Chart option={option} height={Math.max(160, 48 * rows.length + 72)} onReady={setChart} />
      </ChartOrTable>
      {balance && test ? (
        <p className="muted" role="status">
          {t(`cohort.balance.${test}`, { p: balance.p === null || balance.p === undefined ? '—' : fmtValue(balance.p), v: balance.cramers_v === null || balance.cramers_v === undefined ? '—' : fmtValue(balance.cramers_v), n: balance.n })}
          {excluded.length ? ` ${t('cohort.balance.excluded', { levels: excluded.join(', ') })}` : ''}
        </p>
      ) : null}
    </ViewFrame>
  )
}
