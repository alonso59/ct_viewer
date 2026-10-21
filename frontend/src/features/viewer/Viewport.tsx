// Viewport frame over the engine canvas: header, slice slider, crosshair lines, corner text
// (VW-02, 03, 04, 09, 12). The pixels underneath come from the engine; the body is transparent.
import type { CSSProperties, HTMLAttributes, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { useViewerSync, type ViewportId } from '../../state'
import { CtIcon, Icon, codicon } from '../../theme'
import { useViewerLocal } from './local'
import { Render3dControls } from './Render3dControls'
import { CROSS, ORIENTATION, isPlane } from './model/layouts'
import type { Plane, PlaneView, Vec3 } from './model/types'

export const PLANE_COLOR: Record<ViewportId, string> = {
  axial: 'var(--plane-axial)',
  sagittal: 'var(--plane-sagittal)',
  coronal: 'var(--plane-coronal)',
  '3d': 'var(--plane-3d)',
}
const PLANE_ICON = { axial: 'plane-axial', sagittal: 'plane-sagittal', coronal: 'plane-coronal', '3d': 'view-3d' } as const

export type MeshState = 'idle' | 'building' | 'error'

interface Props {
  id: ViewportId
  active: boolean
  plane: PlaneView | null
  ras?: Vec3
  hasMask: boolean
  canSurface?: boolean
  maximized: boolean
  onMaximize: () => void
  /** VW-26 fit this view to its tile */
  onFit: () => void
  onGoto: (index: number) => void
  meshState: MeshState
  bodyProps: HTMLAttributes<HTMLDivElement>
  /** VW-22 probe of this view (only the hovered one), drawn at its bottom-left above the slider */
  probe?: ReactNode
}

export function Viewport({ id, active, plane, ras, hasMask, canSurface = false, maximized, onMaximize, onFit, onGoto, meshState, bodyProps, probe }: Props) {
  const { t } = useTranslation()
  const tool = useViewerSync((s) => s.tool)
  const color = PLANE_COLOR[id]
  return (
    <section
      className="vp"
      aria-label={t(`viewer.plane.${id}`)}
      onDoubleClick={(e) => {
        if ((e.target as HTMLElement).closest('.vp-header')) onMaximize()
      }}
    >
      <header className="vp-header">
        <span className="vp-chip" style={{ background: color }} />
        <span style={{ color, display: 'inline-flex' }}>
          <CtIcon name={PLANE_ICON[id]} />
        </span>
        <span className="vp-title">{t(`viewer.plane.${id}`)}</span>
        {plane ? <span className="vp-index">{t('viewer.sliceOf', { index: plane.index, total: plane.total })}</span> : null}
        {id === '3d' ? <Render3dControls active={active} hasMask={hasMask} canSurface={canSurface} meshState={meshState} /> : null}
        <button type="button" className="icon-btn vp-fit" aria-label={t('viewer.fit')} title={t('viewer.fit')} onClick={onFit}>
          <Icon spec={codicon('layout-centered')} />
        </button>
        <button type="button" className="icon-btn vp-max" aria-label={t(maximized ? 'viewer.restore' : 'viewer.maximize')} title={t(maximized ? 'viewer.restore' : 'viewer.maximize')} onClick={onMaximize}>
          <Icon spec={codicon(maximized ? 'screen-normal' : 'screen-full')} />
        </button>
      </header>
      <div className="vp-body" data-tile={id} data-tool={isPlane(id) ? tool : 'orbit'} {...bodyProps}>
        {isPlane(id) ? <PlaneOverlay plane={id} view={plane} /> : <Overlay3d hasMask={hasMask} ras={ras} />}
        {probe}
      </div>
      {isPlane(id) && plane ? (
        <input
          className="vp-slider"
          type="range"
          min={1}
          max={plane.total}
          value={plane.index}
          aria-label={t('vw.slice', { index: plane.index, total: plane.total })}
          style={{ '--vp-plane': color } as CSSProperties}
          onChange={(e) => onGoto(+e.target.value)}
        />
      ) : null}
    </section>
  )
}

function PlaneOverlay({ plane, view }: { plane: Plane; view: PlaneView | null }) {
  const { t } = useTranslation()
  const ww = useViewerSync((s) => s.ww)
  const wl = useViewerSync((s) => s.wl)
  const crosshair = useViewerSync((s) => s.crosshair)
  const annotations = useViewerLocal((s) => s.scene3d.annotations)
  const [left, right, top, bottom] = ORIENTATION[plane]
  const [vLine, hLine] = CROSS[plane]
  return (
    <div className="vp-overlay">
      {crosshair && view?.cross ? (
        <>
          <span className="vp-cross-v" style={{ left: view.cross[0], background: PLANE_COLOR[vLine] }} />
          <span className="vp-cross-h" style={{ top: view.cross[1], background: PLANE_COLOR[hLine] }} />
        </>
      ) : null}
      {annotations !== 'none' ? <>
      <span className="vp-orient vp-orient-l">{left}</span>
      <span className="vp-orient vp-orient-r">{right}</span>
      <span className="vp-orient vp-orient-t">{top}</span>
      <span className="vp-orient vp-orient-b">{bottom}</span>
      </> : null}
      {annotations !== 'none' ? <>
      <span className="vp-corner vp-corner-tl num">{t('viewer.wlShort', { ww, wl })}</span>
      </> : null}
      {annotations !== 'none' && view && Math.abs(view.zoom - 1) > 0.01 ? <span className="vp-corner vp-corner-tr num">{t('viewer.zoom', { zoom: Math.round(view.zoom * 100) })}</span> : null}
    </div>
  )
}

function Overlay3d({ hasMask, ras }: { hasMask: boolean; ras?: Vec3 }) {
  const { t } = useTranslation()
  const annotations = useViewerLocal((s) => s.scene3d.annotations)
  const background = useViewerLocal((s) => s.scene3d.background)
  if (annotations === 'none') return null
  return (
    <div className="vp-overlay" data-3d-background={background}>
      {annotations === 'full' && ras ? <span className="vp-corner vp-corner-tl">{t('vw.render.ras', { value: ras.map((n) => n.toFixed(1)).join(', ') })}</span> : null}
      {!hasMask ? <span className="vp-corner vp-corner-bl">{t('viewer.noSegmentation')}</span> : null}
    </div>
  )
}
