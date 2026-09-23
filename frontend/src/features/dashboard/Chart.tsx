// ECharts wrapper (canvas). Colors are read from tokens at render time (UI-11, DB-07).
import { BarChart, HeatmapChart, ScatterChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, BrushComponent, ToolboxComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

import { useSettings } from '../../state'
import { token } from '../../theme'

echarts.use([BarChart, ScatterChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, BrushComponent, ToolboxComponent, CanvasRenderer])

export type ChartOption = echarts.EChartsCoreOption
export type ChartInstance = echarts.ECharts

export function palette(): string[] {
  return Array.from({ length: 8 }, (_, i) => token(`--cat-${i + 1}`))
}

export function baseOption(): ChartOption {
  const fg = token('--fg')
  const muted = token('--fg-muted')
  const border = token('--border-muted')
  const axis = { axisLine: { lineStyle: { color: border } }, axisLabel: { color: muted, fontSize: 11 }, splitLine: { lineStyle: { color: border } }, nameTextStyle: { color: muted } }
  return {
    backgroundColor: 'transparent',
    color: palette(),
    textStyle: { color: fg, fontFamily: token('--font-ui') },
    grid: { left: 52, right: 16, top: 36, bottom: 40, containLabel: false },
    tooltip: { backgroundColor: token('--bg-overlay'), borderColor: token('--border'), textStyle: { color: fg, fontSize: 12 } },
    legend: { textStyle: { color: muted, fontSize: 11 }, top: 0, right: 0, itemWidth: 10, itemHeight: 10 },
    xAxis: axis,
    yAxis: axis,
  }
}

/** Merge a view option over the tokenized base, one level deep for the shared components */
export function withBase(option: ChartOption): ChartOption {
  const base = baseOption() as Record<string, unknown>
  const o = option as Record<string, unknown>
  const out: Record<string, unknown> = { ...base, ...o }
  for (const k of ['legend', 'tooltip', 'grid', 'xAxis', 'yAxis', 'textStyle']) {
    if (base[k] && o[k] && typeof o[k] === 'object' && !Array.isArray(o[k])) out[k] = { ...(base[k] as object), ...(o[k] as object) }
  }
  return out
}

export function Chart({ option, onClick, onReady, height = '100%' }: {
  option: ChartOption
  onClick?: (p: { data?: unknown; dataIndex: number; seriesIndex?: number }) => void
  onReady?: (c: ChartInstance) => void
  height?: number | string
}) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<ChartInstance | null>(null)
  const latest = useRef({ option, onClick, onReady })
  const theme = useSettings((s) => s.theme)
  useEffect(() => {
    latest.current = { option, onClick, onReady }
  })
  // Init lazily once the container has a size (hidden tabs start at 0 × 0)
  useEffect(() => {
    const node = el.current
    if (!node) return
    const ro = new ResizeObserver(() => {
      if (!node.clientWidth || !node.clientHeight) return
      if (!chart.current) {
        const c = echarts.init(node, undefined, { renderer: 'canvas' })
        chart.current = c
        c.setOption(withBase(latest.current.option), true)
        c.on('click', (p) => latest.current.onClick?.(p as never))
        latest.current.onReady?.(c)
      } else chart.current.resize()
    })
    ro.observe(node)
    return () => {
      ro.disconnect()
      chart.current?.dispose()
      chart.current = null
    }
  }, [])
  useEffect(() => {
    const c = chart.current
    if (c && !c.isDisposed()) c.setOption(withBase(option), true)
  }, [option, theme])
  return <div ref={el} style={{ width: '100%', height }} />
}
