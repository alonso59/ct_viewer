// Scatter of items with colour levels, hover, click-through, context menu and brush selection
// (DB-03/04/07). Used by the embedding, feature-vs-volume, association and consistency views.
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { fmtNum } from '../../../lib'
import { token } from '../../../theme'
import { Chart, brushOption, brushed, type ChartInstance, type ChartOption } from '../Chart'
import { openRef, useItemMenu, useLevelColors, useSelection, type ItemRef } from './common'

export interface ScatterPoint extends ItemRef {
  x: number
  y: number
  level: string | null
  /** Extra tooltip line (e.g. curation status) */
  note?: string
}

interface Datum {
  value: [number, number]
  ref: ScatterPoint
  itemStyle: Record<string, unknown>
}

export function Scatter({ runId, points, xName, yName, levelName, markLines, onReady }: {
  runId: string
  points: ScatterPoint[]
  xName: string
  yName: string
  levelName: (l: string | null) => string
  /** Horizontal reference lines (e.g. Bland–Altman bias and limits) */
  markLines?: { y: number; label: string }[]
  onReady?: (c: ChartInstance) => void
}) {
  const { t } = useTranslation()
  const sel = useSelection(runId)
  const levels = useMemo(() => [...new Set(points.map((p) => p.level))].sort((a, b) => (a ?? '').localeCompare(b ?? '')), [points])
  const color = useLevelColors(levels)
  const option = useMemo<ChartOption>(() => {
    const series = levels.map((level, i) => ({
      name: levelName(level),
      type: 'scatter',
      symbolSize: (_: unknown, p: { data: Datum }) => (sel.selected.has(p.data.ref.item_id) ? 11 : 8),
      large: points.length > 5000,
      data: points
        .filter((p) => p.level === level)
        .map<Datum>((p) => ({ value: [p.x, p.y], ref: p, itemStyle: sel.style(p.item_id, color(p.level)) })),
      ...(i === 0 && markLines?.length
        ? {
            markLine: {
              symbol: 'none',
              silent: true,
              lineStyle: { color: token('--fg-muted'), type: 'dashed' },
              label: { color: token('--fg-muted'), fontSize: 10, formatter: (p: { name: string }) => p.name },
              data: markLines.map((m) => ({ yAxis: m.y, name: m.label })),
            },
          }
        : {}),
    }))
    return {
      ...brushOption(),
      legend: levels.length > 1 ? { data: levels.map(levelName) } : { show: false },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: Datum }) =>
          [p.data.ref.item_id, `${xName}: ${fmtNum(p.data.ref.x)}`, `${yName}: ${fmtNum(p.data.ref.y)}`, p.data.ref.note].filter(Boolean).join('<br/>'),
      },
      xAxis: { type: 'value', name: xName, nameLocation: 'middle', nameGap: 26, scale: true },
      yAxis: { type: 'value', name: yName, scale: true },
      series,
    }
  }, [points, levels, levelName, color, sel, xName, yName, markLines])
  if (!points.length) return <div className="empty">{t('dashboard.noPoints')}</div>
  return (
    <Chart
      option={option}
      onReady={onReady}
      onClick={(p) => openRef((p.data as Datum | undefined)?.ref)}
      onContextMenu={(p, x, y) => {
        const ref = (p.data as Datum | undefined)?.ref
        if (ref) useItemMenu.getState().open(ref, x, y)
      }}
      onBrush={(areas) => sel.select(brushed(points.map((p) => ({ x: p.x, y: p.y, id: p.item_id })), areas))}
    />
  )
}
