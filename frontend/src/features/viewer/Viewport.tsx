// P0.5 viewport placeholder: one static mid-slice per plane with live W/L, zoom/pan, label overlay,
// per-plane accent colors and crosshair (VW-04). P3 replaces this with the NiiVue engine.
import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent } from 'react'
import { useTranslation } from 'react-i18next'

import type { ItemRecord, LabelDef, Plane, SliceSet } from '../../api'
import { hexToRgb, renderSlice } from '../../lib'
import { useViewerSync, type ViewportId } from '../../state'
import { CtIcon, Icon, codicon } from '../../theme'

export const PLANE_COLOR: Record<ViewportId, string> = {
  axial: 'var(--plane-axial)',
  sagittal: 'var(--plane-sagittal)',
  coronal: 'var(--plane-coronal)',
  '3d': 'var(--plane-3d)',
}
const PLANE_ICON = { axial: 'plane-axial', sagittal: 'plane-sagittal', coronal: 'plane-coronal', '3d': 'view-3d' } as const

// Which planes cross each 2D view: vertical line, horizontal line (3D Slicer convention)
const CROSS: Record<Plane, [ViewportId, ViewportId]> = {
  axial: ['sagittal', 'coronal'],
  coronal: ['sagittal', 'axial'],
  sagittal: ['coronal', 'axial'],
}

function physicalSize(plane: Plane, shape: number[], spacing: number[]): [number, number] {
  const [nx = 1, ny = 1, nz = 1] = shape
  const [sx = 1, sy = 1, sz = 1] = spacing
  if (plane === 'axial') return [nx * sx, ny * sy]
  if (plane === 'coronal') return [nx * sx, nz * sz]
  return [ny * sy, nz * sz]
}

export function sliceIndex(plane: Plane, shape: number[]): [number, number] {
  const [nx = 1, ny = 1, nz = 1] = shape
  const n = plane === 'axial' ? nz : plane === 'coronal' ? ny : nx
  return [(n >> 1) + 1, n]
}

interface Props {
  id: ViewportId
  item: ItemRecord
  /** null = still loading; undefined = no preview for this item */
  slices: SliceSet | null | undefined
  labels: LabelDef[]
  onMaximize: () => void
  maximized: boolean
}

export function Viewport({ id, item, slices, labels, onMaximize, maximized }: Props) {
  const { t } = useTranslation()
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
        {id !== '3d' && item.geometry ? (
          <span className="vp-index num">
            {t('viewer.sliceOf', { index: sliceIndex(id, item.geometry.shape)[0], total: sliceIndex(id, item.geometry.shape)[1] })}
          </span>
        ) : null}
        <button type="button" className="icon-btn vp-max" aria-label={t(maximized ? 'viewer.restore' : 'viewer.maximize')} title={t(maximized ? 'viewer.restore' : 'viewer.maximize')} onClick={onMaximize}>
          <Icon spec={codicon(maximized ? 'screen-normal' : 'screen-full')} />
        </button>
      </header>
      {id === '3d' ? <View3D item={item} labels={labels} /> : <SliceView plane={id} item={item} slices={slices} labels={labels} />}
    </section>
  )
}

function SliceView({ plane, item, slices, labels }: { plane: Plane; item: ItemRecord; slices: SliceSet | null | undefined; labels: LabelDef[] }) {
  const { t } = useTranslation()
  const canvas = useRef<HTMLCanvasElement>(null)
  const host = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState<[number, number]>([0, 0])
  // Zoom/pan reset when the viewer reset token changes (R)
  const [view, setView] = useState({ token: -1, zoom: 1, pan: [0, 0] as [number, number] })
  const drag = useRef<{ x: number; y: number; ww: number; wl: number; pan: [number, number]; mode: 'window' | 'pan' | 'zoom'; zoom: number } | null>(null)
  const v = useViewerSync()
  const current = view.token === v.resetToken ? view : { zoom: 1, pan: [0, 0] as [number, number] }
  const { zoom, pan } = current
  const setZoom = (f: (z: number) => number) => setView({ token: v.resetToken, pan, zoom: f(zoom) })
  const setPan = (p: [number, number]) => setView({ token: v.resetToken, zoom, pan: p })
  const slice = slices?.image[plane]
  const mask = v.overlay ? slices?.mask?.[plane] : null
  const geometry = item.geometry

  // Fit the physical aspect ratio inside the viewport (contain)
  useLayoutEffect(() => {
    const el = host.current
    if (!el || !geometry) return
    const [pw, ph] = physicalSize(plane, geometry.shape, geometry.spacing)
    const ro = new ResizeObserver(([entry]) => {
      if (!entry) return
      const { width, height } = entry.contentRect
      const s = Math.min(width / pw, height / ph) * 0.94
      setBox([pw * s, ph * s])
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [plane, geometry])

  useEffect(() => {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx || !slice) return
    const lab = new Map<number, [number, number, number, number]>()
    for (const l of labels) {
      const visible = v.labelVisibility[l.value] ?? l.visible
      if (visible) lab.set(l.value, [...hexToRgb(l.color), Math.min(1, (v.labelOpacity[l.value] ?? l.opacity) * 2 * v.overlayOpacity)])
    }
    renderSlice(ctx, { w: slice.w, h: slice.h, image: slice.data, mask: mask?.data, ww: v.ww, wl: v.wl, labels: lab, outline: v.outline })
  }, [slice, mask, labels, v.ww, v.wl, v.outline, v.labelVisibility, v.labelOpacity, v.overlayOpacity])

  const readout = (e: PointerEvent) => {
    const el = canvas.current
    if (!el || !slice || !geometry) return
    const r = el.getBoundingClientRect()
    const c = Math.floor(((e.clientX - r.left) / r.width) * slice.w)
    const row = Math.floor(((e.clientY - r.top) / r.height) * slice.h)
    if (c < 0 || row < 0 || c >= slice.w || row >= slice.h) {
      v.set({ cursor: null })
      return
    }
    const [nx = 1, ny = 1, nz = 1] = geometry.shape
    const ijk: [number, number, number] =
      plane === 'axial' ? [c, ny - 1 - row, nz >> 1] : plane === 'coronal' ? [c, ny >> 1, nz - 1 - row] : [nx >> 1, c, nz - 1 - row]
    const [sx = 1, sy = 1, sz = 1] = geometry.spacing
    const i = row * slice.w + c
    v.set({
      cursor: {
        ijk,
        ras: [+(ijk[0] * sx).toFixed(1), +(ijk[1] * sy).toFixed(1), +(ijk[2] * sz).toFixed(1)],
        value: slice.data[i] ?? 0,
        label: slices?.mask?.[plane].data[i] ?? 0,
      },
    })
  }

  const onDown = (e: PointerEvent) => {
    const mode =
      e.button === 2 || (e.button === 0 && v.tool === 'window')
        ? 'window'
        : e.button === 1 || (e.button === 0 && v.tool === 'pan')
          ? 'pan'
          : e.button === 0 && v.tool === 'zoom'
            ? 'zoom'
            : null
    if (!mode) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, y: e.clientY, ww: v.ww, wl: v.wl, pan, mode, zoom }
  }
  const onMove = (e: PointerEvent) => {
    readout(e)
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x
    const dy = e.clientY - d.y
    if (d.mode === 'window') v.setWindow(d.ww + dx * 4, d.wl - dy * 2)
    else if (d.mode === 'pan') setPan([d.pan[0] + dx, d.pan[1] + dy])
    else setZoom(() => Math.max(0.5, Math.min(8, d.zoom * Math.exp(-dy / 150))))
  }

  if (!slice || !geometry)
    return (
      <div className="vp-body">
        <div className="vp-message">{slices === null ? t('common.loading') : t('viewer.noPreview')}</div>
      </div>
    )

  const [cross1, cross2] = CROSS[plane]
  return (
    <div
      ref={host}
      className="vp-body"
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={() => (drag.current = null)}
      onPointerLeave={() => v.set({ cursor: null })}
      onContextMenu={(e) => e.preventDefault()}
      onWheel={(e) => {
        if (e.ctrlKey || e.metaKey) setZoom((z) => Math.max(0.5, Math.min(8, z * Math.exp(-e.deltaY / 300))))
      }}
      data-tool={v.tool}
    >
      <div className="vp-stage" style={{ width: box[0], height: box[1], transform: `translate(${pan[0]}px, ${pan[1]}px) scale(${zoom})` }}>
        <canvas ref={canvas} width={slice.w} height={slice.h} className="vp-canvas" />
        {v.crosshair ? (
          <>
            <span className="vp-cross-v" style={{ background: PLANE_COLOR[cross1] }} />
            <span className="vp-cross-h" style={{ background: PLANE_COLOR[cross2] }} />
          </>
        ) : null}
      </div>
      <span className="vp-corner vp-corner-tl num">{t('viewer.wlShort', { ww: v.ww, wl: v.wl })}</span>
      <span className="vp-corner vp-corner-bl">{t('viewer.placeholderNote')}</span>
      {zoom !== 1 ? <span className="vp-corner vp-corner-tr num">{t('viewer.zoom', { zoom: Math.round(zoom * 100) })}</span> : null}
    </div>
  )
}

function View3D({ item, labels }: { item: ItemRecord; labels: LabelDef[] }) {
  const { t } = useTranslation()
  if (!item.mask)
    return (
      <div className="vp-body">
        <div className="vp-message">
          <Icon spec={codicon('circle-slash')} size={20} />
          {t('viewer.noSegmentation')}
        </div>
      </div>
    )
  const present = labels.filter((l) => item.labels_present.includes(l.value))
  return (
    <div className="vp-body">
      <div className="vp-message">
        <span style={{ color: 'var(--plane-3d)' }}>
          <CtIcon name="view-3d" size={48} />
        </span>
        <span>{t('viewer.render3dPlaceholder')}</span>
        <span style={{ display: 'flex', gap: 10 }}>
          {present.map((l) => (
            <span key={l.value} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span className="dot" style={{ background: l.color }} />
              {l.name}
            </span>
          ))}
        </span>
      </div>
    </div>
  )
}
