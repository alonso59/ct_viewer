// VW-17 measurement layer: distance, angle and circular ROI mean/SD in HU, drawn in canvas space
// over the tiles and kept in memory for the visible item only (never persisted, ADR-0021).
import { useTranslation } from 'react-i18next'

import { angleDeg, distanceMm, type Measurement } from './model/measure'
import type { Plane, ViewerHandle, ViewState } from './model/types'

const fmt = (v: number, d = 1) => v.toFixed(d)

export function MeasureLayer({ handle, view, items, draft }: { handle: ViewerHandle | null; view: ViewState | null; items: Measurement[]; draft: Measurement | null }) {
  const { t } = useTranslation()
  if (!handle || !view) return null
  const visible = [...items, ...(draft ? [draft] : [])].filter((m) => view.planes[m.tile]?.index === m.slice)
  return (
    <svg className="vp-measure" aria-label={t('vw.measurements')}>
      {visible.map((m) => {
        const pts = m.points.map((p) => handle.canvasAt(p, m.tile as Plane)).filter((p): p is [number, number] => p !== null)
        if (!pts.length) return null
        const last = pts[pts.length - 1]!
        let text = ''
        if (m.kind === 'distance' && m.points.length === 2) text = t('vw.mm', { v: fmt(distanceMm(m.points[0]!, m.points[1]!)) })
        if (m.kind === 'angle' && m.points.length === 3) text = t('vw.deg', { v: fmt(angleDeg(m.points[0]!, m.points[1]!, m.points[2]!)) })
        if (m.kind === 'roi' && m.stats) text = t('vw.roi', { mean: fmt(m.stats.mean), sd: fmt(m.stats.sd), n: m.stats.n, area: fmt(m.stats.areaMm2 / 100, 2) })
        const radius = m.kind === 'roi' && pts.length === 2 ? Math.hypot(pts[1]![0] - pts[0]![0], pts[1]![1] - pts[0]![1]) : 0
        return (
          <g key={m.id} data-kind={m.kind}>
            {m.kind === 'roi' && radius ? <circle cx={pts[0]![0]} cy={pts[0]![1]} r={radius} /> : <polyline points={pts.map((p) => p.join(',')).join(' ')} />}
            {pts.map((p, i) => <circle key={i} className="vp-measure-pt" cx={p[0]} cy={p[1]} r={2.5} />)}
            {text ? <text x={last[0] + 6} y={last[1] - 6}>{text}</text> : null}
          </g>
        )
      })}
    </svg>
  )
}
