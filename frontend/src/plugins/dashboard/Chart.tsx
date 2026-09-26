// ECharts wrapper (canvas). Colors are read from tokens at render time (UI-11, DB-07).
import { BarChart, BoxplotChart, HeatmapChart, ScatterChart } from 'echarts/charts'
import {
  BrushComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

import { fmtValue } from '../../lib'
import { useSettings } from '../../state'
import { token } from '../../theme'

echarts.use([
  BarChart, BoxplotChart, ScatterChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent,
  BrushComponent, ToolboxComponent, MarkLineComponent, CanvasRenderer,
])

export type ChartOption = echarts.EChartsCoreOption
export type ChartInstance = echarts.ECharts

export interface ChartEvent {
  data?: unknown
  dataIndex: number
  seriesIndex?: number
  event?: { event?: MouseEvent }
}

/** A brush area in data coordinates: rect `[[x0, x1], [y0, y1]]` or polygon `[[x, y], …]` */
export interface BrushArea {
  brushType: string
  coordRange: number[][]
}

export function palette(): string[] {
  return Array.from({ length: 8 }, (_, i) => token(`--cat-${i + 1}`))
}

/** A font-size token in px (UI_SHELL §Theme tokens; AUD-A3-14): charts follow the interface size */
export function fontSize(name: '--fs-badge' | '--fs-panel' | '--fs-ui'): number {
  const px = Number.parseFloat(token(name))
  return Number.isFinite(px) && px > 0 ? px : name === '--fs-badge' ? 11 : 12
}

/** Axis styling from the tokens; for views that pass an axis array (not merged by `withBase`) */
export function axisStyle() {
  const muted = token('--fg-muted')
  const border = token('--border-muted')
  // value ticks in the English format without thousands separators (AUD-A3-04)
  const formatter = (v: number | string) => (typeof v === 'number' ? fmtValue(v) : v)
  return { axisLine: { lineStyle: { color: border } }, axisLabel: { color: muted, fontSize: fontSize('--fs-badge'), formatter }, splitLine: { lineStyle: { color: border } }, nameTextStyle: { color: muted, fontSize: fontSize('--fs-badge') } }
}

export function baseOption(): ChartOption {
  const fg = token('--fg')
  const muted = token('--fg-muted')
  const axis = axisStyle()
  return {
    backgroundColor: 'transparent',
    color: palette(),
    textStyle: { color: fg, fontFamily: token('--font-ui'), fontSize: fontSize('--fs-panel') },
    grid: { left: 56, right: 16, top: 32, bottom: 40, containLabel: false },
    tooltip: { backgroundColor: token('--bg-overlay'), borderColor: token('--border'), textStyle: { color: fg, fontSize: fontSize('--fs-panel') } },
    legend: { textStyle: { color: muted, fontSize: fontSize('--fs-badge') }, top: 0, right: 0, itemWidth: 10, itemHeight: 10, type: 'scroll' },
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

/** Brush toolbox (DB-04): rectangle and lasso, top right, above the plot — never over the x-axis
 *  labels (AUD-A3-14). A legend next to it starts at `BRUSH_LEGEND_RIGHT`. */
export const BRUSH_LEGEND_RIGHT = 80
export function brushOption(): ChartOption {
  const muted = token('--fg-muted')
  return {
    toolbox: { right: 0, top: 0, itemSize: 13, iconStyle: { borderColor: muted }, emphasis: { iconStyle: { borderColor: token('--accent') } }, feature: { brush: { type: ['rect', 'polygon', 'clear'] } } },
    brush: { xAxisIndex: 0, throttleType: 'debounce', brushStyle: { borderColor: token('--accent'), borderWidth: 1, color: 'transparent' } },
  }
}

function inPolygon(x: number, y: number, poly: number[][]): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi = 0, yi = 0] = poly[i] ?? []
    const [xj = 0, yj = 0] = poly[j] ?? []
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-12) + xi) inside = !inside
  }
  return inside
}

/** Ids of the points inside any brush area (data coordinates) */
export function brushed(points: { x: number; y: number; id: string }[], areas: BrushArea[]): string[] {
  const hit = new Set<string>()
  for (const a of areas) {
    for (const p of points) {
      if (a.brushType === 'rect') {
        const [xs = [], ys = []] = a.coordRange
        const [x0 = 0, x1 = 0] = xs
        const [y0 = 0, y1 = 0] = ys
        if (p.x >= Math.min(x0, x1) && p.x <= Math.max(x0, x1) && p.y >= Math.min(y0, y1) && p.y <= Math.max(y0, y1)) hit.add(p.id)
      } else if (a.brushType === 'polygon' && inPolygon(p.x, p.y, a.coordRange)) hit.add(p.id)
    }
  }
  return [...hit]
}

export function Chart({ option, onClick, onContextMenu, onBrush, onReady, height = '100%' }: {
  option: ChartOption
  onClick?: (p: ChartEvent) => void
  /** Right click on a data point; client (viewport) pixels */
  onContextMenu?: (p: ChartEvent, x: number, y: number) => void
  /** User brush finished (DB-04); empty areas = cleared */
  onBrush?: (areas: BrushArea[]) => void
  onReady?: (c: ChartInstance) => void
  height?: number | string
}) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<ChartInstance | null>(null)
  const latest = useRef({ option, onClick, onContextMenu, onBrush, onReady })
  const theme = useSettings((s) => s.theme)
  useEffect(() => {
    latest.current = { option, onClick, onContextMenu, onBrush, onReady }
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
        c.on('click', (p) => latest.current.onClick?.(p as unknown as ChartEvent))
        c.on('contextmenu', (p) => {
          const e = (p as unknown as ChartEvent).event?.event
          e?.preventDefault()
          if (e) latest.current.onContextMenu?.(p as unknown as ChartEvent, e.clientX, e.clientY)
        })
        c.on('brushEnd', (p) => latest.current.onBrush?.((p as { areas?: BrushArea[] }).areas ?? []))
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
  return <div ref={el} style={{ width: '100%', height }} onContextMenu={(e) => e.preventDefault()} />
}
