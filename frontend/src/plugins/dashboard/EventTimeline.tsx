import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { CohortTimeline } from '../../api'
import { token } from '../../theme'
import { Chart, SYMBOLS, axisStyle, palette, type ChartInstance, type ChartOption } from './Chart'
import { ChartOrTable, ViewFrame, type CsvRows } from './views/common'

/** One case on a day axis: its scans on one row and its events, coloured by kind, on another.
 *  Days count from the first dated scan; the table lists the same points. */
export function EventTimeline({ timeline }: { timeline: CohortTimeline }) {
  const { t } = useTranslation()
  const [chart, setChart] = useState<ChartInstance | null>(null)
  const all = useMemo(() => timeline.events ?? [], [timeline])
  const kinds = useMemo(() => [...new Set(all.map((e) => e.kind ?? ''))], [all])
  const scans = useMemo(() => (timeline.scans ?? []).filter((s) => s.day !== null && s.day !== undefined), [timeline])
  const events = useMemo(() => all.filter((e) => e.day !== null && e.day !== undefined), [all])
  const option = useMemo<ChartOption>(() => {
    const colors = palette()
    return {
      grid: { left: 72, right: 24, top: 24, bottom: 40 },
      legend: { data: [t('cohort.timeline.scans'), ...kinds.map((k) => k || t('cohort.timeline.noKind'))] },
      tooltip: { trigger: 'item' },
      xAxis: { type: 'value', name: t('cohort.timeline.axis'), nameLocation: 'middle', nameGap: 24, ...axisStyle() },
      yAxis: { type: 'category', data: [t('cohort.timeline.events'), t('cohort.timeline.scans')], ...axisStyle() },
      series: [
        {
          type: 'scatter', name: t('cohort.timeline.scans'), symbol: 'rect', symbolSize: 12, itemStyle: { color: token('--fg-muted') },
          data: scans.map((s) => ({ value: [s.day, t('cohort.timeline.scans')], name: `${s.scan_idx} · ${s.phase}` })),
        },
        ...kinds.map((kind, i) => ({
          type: 'scatter' as const,
          name: kind || t('cohort.timeline.noKind'),
          symbol: SYMBOLS[(i + 1) % SYMBOLS.length],
          symbolSize: 14,
          itemStyle: { color: colors[i % colors.length] },
          data: events.filter((e) => (e.kind ?? '') === kind).map((e) => ({ value: [e.day, t('cohort.timeline.events')], name: `${kind} · ${t('cohort.timeline.dayN', { day: e.day })}` })),
        })),
      ],
    }
  }, [scans, events, kinds, t])
  const rows = (): CsvRows => [
    [t('cohort.timeline.what'), t('cohort.timeline.kind'), t('cohort.timeline.day')],
    ...scans.map((s) => [t('cohort.timeline.scan'), `${s.scan_idx} · ${s.phase}`, s.day]),
    ...all.map((e) => [e.table, e.kind, e.day]),
  ]
  return (
    <ViewFrame name={`timeline-${timeline.case_id}`} chart={chart} csv={rows}>
      <ChartOrTable rows={rows}>
        <Chart option={option} height={200} onReady={setChart} />
      </ChartOrTable>
      {timeline.anchor_scan === null ? <p className="muted" role="note">{t('cohort.timeline.noAnchor')}</p> : null}
    </ViewFrame>
  )
}
