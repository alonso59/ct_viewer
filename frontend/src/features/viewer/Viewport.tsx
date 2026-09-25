// Viewport frame over the engine canvas: header, slice slider, crosshair lines, corner text
// (VW-02, 03, 04, 09, 12). The pixels underneath come from the engine; the body is transparent.
import type { HTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'

import type { LabelDef } from '../../api'
import { useViewerSync, type ViewportId } from '../../state'
import { CtIcon, Icon, codicon } from '../../theme'
import { useViewerLocal } from './local'
import { CROSS, ORIENTATION, isPlane } from './model/layouts'
import type { Plane, PlaneView } from './model/types'

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
  plane: PlaneView | null
  hasMask: boolean
  /** Labels present in this item (3D legend) */
  labels: LabelDef[]
  maximized: boolean
  onMaximize: () => void
  /** VW-26 fit this view to its tile */
  onFit: () => void
  onGoto: (index: number) => void
  meshState: MeshState
  bodyProps: HTMLAttributes<HTMLDivElement>
}

export function Viewport({ id, plane, hasMask, labels, maximized, onMaximize, onFit, onGoto, meshState, bodyProps }: Props) {
  const { t } = useTranslation()
  const tool = useViewerSync((s) => s.tool)
  const color = PLANE_COLOR[id]
  return (
    <section
      className="vp"
      style={{ borderColor: `color-mix(in srgb, ${color} 55%, transparent)` }}
      aria-label={t(`viewer.plane.${id}`)}
      onDoubleClick={(e) => {
        if ((e.target as HTMLElement).closest('.vp-header')) onMaximize()
      }}
    >
      <header className="vp-header">
        <span className="vp-swatch" style={{ background: color }} />
        <span style={{ color, display: 'inline-flex' }}>
          <CtIcon name={PLANE_ICON[id]} />
        </span>
        <span className="vp-title">{t(`viewer.plane.${id}`)}</span>
        {plane ? <span className="vp-index num">{t('viewer.sliceOf', { index: plane.index, total: plane.total })}</span> : null}
        {id === '3d' && hasMask ? <Render3dControls meshState={meshState} /> : null}
        <button type="button" className="icon-btn vp-fit" aria-label={t('viewer.fit')} title={t('viewer.fit')} onClick={onFit}>
          <Icon spec={codicon('layout-centered')} />
        </button>
        <button type="button" className="icon-btn vp-max" aria-label={t(maximized ? 'viewer.restore' : 'viewer.maximize')} title={t(maximized ? 'viewer.restore' : 'viewer.maximize')} onClick={onMaximize}>
          <Icon spec={codicon(maximized ? 'screen-normal' : 'screen-full')} />
        </button>
      </header>
      <div className="vp-body" data-tile={id} data-tool={isPlane(id) ? tool : 'orbit'} {...bodyProps}>
        {isPlane(id) ? <PlaneOverlay plane={id} view={plane} /> : <Overlay3d hasMask={hasMask} labels={labels} />}
      </div>
      {isPlane(id) && plane ? (
        <input
          className="vp-slider"
          type="range"
          min={1}
          max={plane.total}
          value={plane.index}
          aria-label={t('vw.slice', { index: plane.index, total: plane.total })}
          style={{ accentColor: color }}
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
      <span className="vp-orient vp-orient-l">{left}</span>
      <span className="vp-orient vp-orient-r">{right}</span>
      <span className="vp-orient vp-orient-t">{top}</span>
      <span className="vp-orient vp-orient-b">{bottom}</span>
      <span className="vp-corner vp-corner-tl num">{t('viewer.wlShort', { ww, wl })}</span>
      {view && Math.abs(view.zoom - 1) > 0.01 ? <span className="vp-corner vp-corner-tr num">{t('viewer.zoom', { zoom: Math.round(view.zoom * 100) })}</span> : null}
    </div>
  )
}

function Overlay3d({ hasMask, labels }: { hasMask: boolean; labels: LabelDef[] }) {
  const { t } = useTranslation()
  if (!hasMask)
    return (
      <div className="vp-message">
        <Icon spec={codicon('circle-slash')} size={20} />
        {t('viewer.noSegmentation')}
      </div>
    )
  return (
    <div className="vp-overlay">
      <span className="vp-corner vp-corner-bl vp-legend">
        {labels.map((l) => (
          <span key={l.value}>
            <span className="dot" style={{ background: l.color }} />
            {l.name}
          </span>
        ))}
      </span>
    </div>
  )
}

function Render3dControls({ meshState }: { meshState: MeshState }) {
  const { t } = useTranslation()
  const volume3d = useViewerLocal((s) => s.volume3d)
  const surfaces = useViewerLocal((s) => s.surfaces)
  const blend = useViewerLocal((s) => s.blend)
  const set = useViewerLocal.setState
  const meshTitle = meshState === 'building' ? t('vw.meshBuilding') : meshState === 'error' ? t('vw.meshError') : t('vw.render.surfaces')
  return (
    <span className="vp-3d-tools">
      <button type="button" className="icon-btn" aria-pressed={volume3d} title={t('vw.render.volume')} aria-label={t('vw.render.volume')} onClick={() => set({ volume3d: !volume3d })}>
        <CtIcon name="view-3d" />
      </button>
      <button type="button" className="icon-btn" aria-pressed={surfaces} title={meshTitle} aria-label={t('vw.render.surfaces')} onClick={() => set({ surfaces: !surfaces })}>
        <Icon spec={codicon(meshState === 'building' ? 'loading' : meshState === 'error' ? 'warning' : 'symbol-structure')} />
      </button>
      <input className="vp-blend" type="range" min={0} max={1} step={0.05} value={blend} title={t('vw.render.blend')} aria-label={t('vw.render.blend')} onChange={(e) => set({ blend: +e.target.value })} />
    </span>
  )
}
