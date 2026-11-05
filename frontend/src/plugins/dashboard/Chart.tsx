// ECharts wrapper (canvas). Colors are read from tokens at render time.
import { BarChart, BoxplotChart, HeatmapChart, ScatterChart } from 'echarts/charts'
import {
  AriaComponent,
  BrushComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer, SVGRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

import { fmtValue } from '../../lib'
import { useSettings } from '../../state'
import { token } from '../../theme'

echarts.use([
  BarChart, BoxplotChart, ScatterChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent,
  BrushComponent, ToolboxComponent, MarkLineComponent, AriaComponent, CanvasRenderer, SVGRenderer,
])

/** Series shapes, so the series of a chart differ by more than colour */
export const SYMBOLS = ['circle', 'rect', 'triangle', 'diamond', 'pin', 'arrow']

const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

export type ChartOption = echarts.EChartsCoreOption
export type ChartInstance = echarts.ECharts

interface ChartEvent {
  data?: unknown
  dataIndex: number
  seriesIndex?: number
  event?: { event?: MouseEvent }
}

/** A brush area in data coordinates: rect `[[x0, x1], [y0, y1]]` or polygon `[[x, y], …]` */
interface BrushArea {
  brushType: string
  coordRange: number[][]
}

export type ChartImageKind = 'png' | 'png-light' | 'svg'

/** Theme colours a light export swaps for the light theme's */
const LIGHT_SWAPS = ['--fg', '--fg-muted', '--border', '--border-muted', '--bg-overlay']

/** Token values with the light theme applied for a moment (styles resolve synchronously) */
function inLightTheme<T>(read: () => T): T {
  const root = document.documentElement
  const was = root.dataset.theme
  root.dataset.theme = 'light'
  try {
    return read()
  } finally {
    if (was === undefined) delete root.dataset.theme
    else root.dataset.theme = was
  }
}

const swapColors = (node: unknown, swaps: Map<string, string>): unknown => {
  if (typeof node === 'string') return swaps.get(node) ?? node
  if (Array.isArray(node)) return node.map((x) => swapColors(x, swaps))
  if (node && typeof node === 'object') return Object.fromEntries(Object.entries(node).map(([k, v]) => [k, swapColors(v, swaps)]))
  return node
}

/** The drawn chart as a data URL: `png` in the theme, `png-light` on white with dark text,
 *  `svg` as a vector in the theme's colours */
export function chartImage(chart: ChartInstance, kind: ChartImageKind): string {
  const bg = token('--bg-editor')
  if (kind === 'png') return chart.getDataURL({ pixelRatio: 2, backgroundColor: bg })
  const width = chart.getWidth()
  const height = chart.getHeight()
  const light = kind === 'png-light' ? inLightTheme(() => ({ bg: token('--bg-editor'), colors: LIGHT_SWAPS.map((name) => token(name)) })) : null
  const swaps = new Map(light ? LIGHT_SWAPS.map((name, i) => [token(name), light.colors[i] ?? ''] as [string, string]) : [])
  const option = { ...(swapColors(chart.getOption(), swaps) as Record<string, unknown>), animation: false }
  if (kind === 'svg') {
    const svg = echarts.init(null, undefined, { renderer: 'svg', ssr: true, width, height })
    svg.setOption({ ...option, backgroundColor: bg })
    const text = svg.renderToSVGString()
    svg.dispose()
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(text)}`
  }
  const node = document.createElement('div')
  node.style.cssText = `position:fixed;left:-10000px;width:${width}px;height:${height}px`
  document.body.append(node)
  const drawn = echarts.init(node, undefined, { renderer: 'canvas', width, height })
  drawn.setOption(option)
  const url = drawn.getDataURL({ pixelRatio: 2, backgroundColor: light?.bg ?? bg })
  drawn.dispose()
  node.remove()
  return url
}

export function palette(): string[] {
  return Array.from({ length: 8 }, (_, i) => token(`--cat-${i + 1}`))
}

/** A font-size token in px, so charts follow the interface size */
export function fontSize(name: '--fs-badge' | '--fs-panel' | '--fs-ui'): number {
  const px = Number.parseFloat(token(name))
  return Number.isFinite(px) && px > 0 ? px : name === '--fs-badge' ? 11 : 12
}

/** Axis styling from the tokens; for views that pass an axis array (not merged by `withBase`) */
export function axisStyle() {
  const muted = token('--fg-muted')
  const border = token('--border-muted')
  // value ticks in the English format without thousands separators
  const formatter = (v: number | string) => (typeof v === 'number' ? fmtValue(v) : v)
  return { axisLine: { lineStyle: { color: border } }, axisLabel: { color: muted, fontSize: fontSize('--fs-badge'), formatter }, splitLine: { lineStyle: { color: border } }, nameTextStyle: { color: muted, fontSize: fontSize('--fs-badge') } }
}

function baseOption(): ChartOption {
  const fg = token('--fg')
  const muted = token('--fg-muted')
  const axis = axisStyle()
  return {
    backgroundColor: 'transparent',
    // the canvas gets role="img" and a description of its series
    aria: { enabled: true },
    animation: !reducedMotion(),
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
function withBase(option: ChartOption): ChartOption {
  const base = baseOption() as Record<string, unknown>
  const o = option as Record<string, unknown>
  const out: Record<string, unknown> = { ...base, ...o }
  for (const k of ['aria', 'legend', 'tooltip', 'grid', 'xAxis', 'yAxis', 'textStyle']) {
    if (base[k] && o[k] && typeof o[k] === 'object' && !Array.isArray(o[k])) out[k] = { ...(base[k] as object), ...(o[k] as object) }
  }
  return out
}

/** Brush toolbox: rectangle and lasso, top right above the plot so it never covers the x-axis
 *  labels. A legend next to it starts at `BRUSH_LEGEND_RIGHT`. */
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
  /** User brush finished; empty areas = cleared */
  onBrush?: (areas: BrushArea[]) => void
  onReady?: (c: ChartInstance) => void
  height?: number | string
}) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<ChartInstance | null>(null)
  const latest = useRef({ option, onClick, onContextMenu, onBrush, onReady })
  const theme = useSettings((s) => s.theme)
  const size = useSettings((s) => s.uiSize)
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
  }, [option, theme, size])
  return <div ref={el} style={{ width: '100%', height }} onContextMenu={(e) => e.preventDefault()} />
}
