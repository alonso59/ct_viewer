// One case tab's viewer: a single engine canvas under the viewport frames (VW-01..09, 12..15).
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type HTMLAttributes, type PointerEvent as RPointerEvent, type WheelEvent as RWheelEvent } from 'react'
import { useTranslation } from 'react-i18next'

import type { ItemRecord, LabelDef } from '../../api'
import { Progress } from '../../lib'
import { useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { createViewer, hasWebgl2, VolumeFetchError } from './engine'
import { useViewerLocal } from './local'
import { fetchMesh } from './meshes'
import { isPlane, visibleViewports } from './model/layouts'
import type { LabelStyle, LoadProgress, Plane, TileRect, Vec3, ViewerHandle, ViewportId, ViewState } from './model/types'
import { dicomWindowOf, dragWindow, effectiveModality, isCt, modalityKey } from './model/wl'
import { MeasureLayer } from './Measurements'
import { NEEDED, type MeasureKind, type Measurement } from './model/measure'
import { Viewport, type MeshState } from './Viewport'

export interface SurfaceProps {
  item: ItemRecord
  imageUrl: string
  maskUrl?: string
  labels: LabelDef[]
  /** API-25 URL for a label's surface mesh */
  meshUrl?: (label: number) => string
  /** Visible tab (keyboard, store sync, VW-16 context) */
  active: boolean
  /** VW-14: false = volumes released */
  loaded: boolean
  /** VW-22 header info: the item's DICOM tags, when it has them (API-22 or the Open-mode tags) */
  tags?: () => Promise<Record<string, unknown>>
}

/** Focus handling of the viewer's container: `when: 'viewer'` shortcuts fire while it has focus */
export const viewerFocusProps: HTMLAttributes<HTMLDivElement> = {
  tabIndex: -1,
  onFocus: () => useViewerSync.setState({ viewerFocused: true }),
  onBlur: (e) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) useViewerSync.setState({ viewerFocused: false })
  },
  onPointerDown: (e) => {
    if (!(e.target as HTMLElement).closest('button, input, select')) e.currentTarget.focus()
  },
}

/** VW-25: the initial CT window of the store (a preset name when it matches one) */
function applyCtWindow() {
  const s = useViewerSync.getState()
  const [ww, wl] = s.ctWindow
  if (ww === 400 && wl === 50) s.setPreset('soft_tissue')
  else s.setWindow(ww, wl)
}

/** Keyed by the load it belongs to, so a new load starts as "loading" without a reset render */
type LoadState = { key: string; phase: 'loading' | 'ready' | 'error'; progress: LoadProgress | null; error: { status: number; code: string | null; message: string } | null; maskError: boolean }
const LOADING = (key: string): LoadState => ({ key, phase: 'loading', progress: null, error: null, maskError: false })

interface Drag {
  mode: 'pick' | 'window' | 'pan' | 'zoom' | 'orbit'
  tile: ViewportId
  x: number
  y: number
  start: [number, number]
}

const sameGeometry = (a: ItemRecord['geometry'], b: ItemRecord['geometry']) =>
  !!a && !!b && a.shape.join() === b.shape.join() && a.spacing.every((s, i) => Math.abs(s - (b.spacing[i] ?? NaN)) < 1e-4)

export function ViewerSurface({ item, imageUrl, maskUrl, labels, meshUrl, active, loaded, tags }: SurfaceProps) {
  const { t } = useTranslation()
  const host = useRef<HTMLDivElement>(null)
  const canvasHost = useRef<HTMLDivElement>(null)
  const grid = useRef<HTMLDivElement>(null)
  const [handle, setHandle] = useState<ViewerHandle | null>(null)
  const [loadState, setLoad] = useState<LoadState>(LOADING(''))
  const [view, setView] = useState<ViewState | null>(null)
  const [webgl] = useState(hasWebgl2)
  const drag = useRef<Drag | null>(null)
  const space = useRef(false)
  const prev = useRef<{ geometry: ItemRecord['geometry']; ras: Vec3 } | null>(null)

  const v = useViewerSync()
  const local = useViewerLocal()
  const hasMask = !!maskUrl && !!item.mask
  const viewports = visibleViewports(v.layout, v.maximized)
  const [handleId, setHandleId] = useState(0)
  const loadKey = `${handleId}|${item.item_id}|${imageUrl}|${hasMask ? maskUrl : ''}`
  const load = loadState.key === loadKey ? loadState : LOADING(loadKey)

  // Engine lifecycle: one per tab while it holds volumes (VW-14)
  useEffect(() => {
    const c = canvasHost.current
    if (!loaded || !c || !webgl) return
    let h: ViewerHandle | null = null
    let cancelled = false
    void createViewer(c).then((created) => {
      if (cancelled) return created.dispose()
      h = created
      setHandle(created)
      setHandleId((n) => n + 1)
    })
    return () => {
      cancelled = true
      setHandle(null)
      h?.dispose()
    }
  }, [loaded, webgl])

  // Load (and reload when the item changes or the tab gets its budget back)
  useEffect(() => {
    if (!handle) return
    const ac = new AbortController()
    const keep = prev.current && sameGeometry(prev.current.geometry, item.geometry) ? prev.current.ras : null
    const key = loadKey
    const update = (patch: Partial<LoadState>) => setLoad((s) => ({ ...(s.key === key ? s : LOADING(key)), ...patch }))
    const { ww, wl } = useViewerSync.getState()
    handle.setWindow(ww, wl)
    handle
      .load(item, {
        imageUrl,
        maskUrl: hasMask ? maskUrl : undefined,
        signal: ac.signal,
        onProgress: (progress) => update({ progress }),
        onImage: () => {
          // VW-15: same geometry → keep crosshair and W/L; otherwise start centred
          if (keep) handle.setCrosshair(keep)
          else {
            // VW-22/25: the DICOM header window first (when enabled), else the modality default
            const s = useViewerSync.getState()
            const header = s.useDicomWindow ? dicomWindowOf(item) : null
            if (header) s.setWindow(header[0], header[1])
            else if (isCt({ modality: effectiveModality(item, s.modalityOverride, s.defaultModality).value })) applyCtWindow()
            else {
              const [dw, dl] = handle.defaultWindow()
              s.setWindow(dw, dl)
            }
          }
          update({ phase: 'ready' })
        },
      })
      .then(() => {
        if (!ac.signal.aborted) update({ maskError: handle.maskError !== null })
      })
      .catch((e: unknown) => {
        if (ac.signal.aborted) return
        const err = e instanceof VolumeFetchError ? { status: e.status, code: e.code, message: e.message } : { status: 0, code: null, message: e instanceof Error ? e.message : String(e) }
        update({ phase: 'error', error: err })
      })
    return () => ac.abort()
    // loadKey covers handle/item/urls
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadKey])

  // VW-05: publish the visible item's modality (the selector shows only when it is assumed), and
  // re-window when the user changes an assumed modality: CT → soft tissue, other → percentiles
  const mKey = modalityKey(item)
  const override = useViewerSync((s) => s.modalityOverride[mKey])
  const fallback = useViewerSync((s) => s.defaultModality)
  const modality = effectiveModality(item, override ? { [mKey]: override } : {}, fallback)
  useEffect(() => {
    if (!active) return
    useViewerSync.setState({ activeModality: { key: mKey, value: modality.value, assumed: modality.assumed } })
    return () => {
      if (useViewerSync.getState().activeModality?.key === mKey) useViewerSync.setState({ activeModality: null })
    }
  }, [active, mKey, modality.value, modality.assumed])
  const windowedFor = useRef<{ key: string; value: string } | null>(null)
  useEffect(() => {
    if (!handle || load.phase !== 'ready') return
    const w = windowedFor.current
    windowedFor.current = { key: mKey, value: modality.value }
    // A new item keeps the window onImage chose (VW-15); only a changed choice re-windows
    if (!w || w.key !== mKey || w.value === modality.value) return
    if (isCt({ modality: modality.value })) applyCtWindow()
    else {
      const [dw, dl] = handle.defaultWindow()
      useViewerSync.getState().setWindow(dw, dl)
    }
  }, [handle, load.phase, mKey, modality.value])

  // Remember geometry + crosshair for VW-15 on the next item
  useEffect(() => {
    if (view) prev.current = { geometry: item.geometry, ras: view.ras }
  }, [view, item.geometry])

  useEffect(() => {
    if (!handle) return
    const offView = handle.onView(setView)
    const offCursor = handle.onCursor((cursor) => useViewerSync.setState({ cursor }))
    return () => {
      offView()
      offCursor()
    }
  }, [handle])

  // Store → engine
  useEffect(() => handle?.setWindow(v.ww, v.wl), [handle, v.ww, v.wl])
  useEffect(() => handle?.setDisplay(v.display), [handle, v.display])
  const styles = useMemo<LabelStyle[]>(
    () => labels.map((l) => ({ value: l.value, color: l.color, visible: v.labelVisibility[l.value] ?? l.visible, opacity: Math.min(1, (v.labelOpacity[l.value] ?? l.opacity) * 2), outline: v.outline })),
    [labels, v.labelVisibility, v.labelOpacity, v.outline],
  )
  useEffect(() => handle?.setLabels(styles), [handle, styles])
  useEffect(() => handle?.setOverlay({ visible: v.overlay, opacity: v.overlayOpacity }), [handle, v.overlay, v.overlayOpacity])
  useEffect(() => handle?.setLinkedZoom(local.linkZoom), [handle, local.linkZoom])
  useEffect(() => handle?.setRender({ volume: local.volume3d, labels: local.surfaces, blend: local.blend }), [handle, local.volume3d, local.surfaces, local.blend])
  const resetToken = useRef(v.resetToken)
  useEffect(() => {
    if (resetToken.current === v.resetToken) return
    resetToken.current = v.resetToken
    if (active) handle?.resetView()
  }, [handle, v.resetToken, active])
  useEffect(() => {
    if (active && handle) {
      useViewerLocal.setState({ active: handle, info: { item, tags } })
      return () => {
        if (useViewerLocal.getState().active === handle) useViewerLocal.setState({ active: null, info: null })
      }
    }
  }, [active, handle, item, tags])

  // VW-17 measurements: in memory for the visible item; cleared on a new item or on request
  const measureSeq = useRef(0)
  const [measures, setMeasures] = useState<{ key: string; items: Measurement[]; draft: Measurement | null }>({ key: '', items: [], draft: null })
  const mine = measures.key === `${loadKey}|${v.measureClear}` ? measures : { key: `${loadKey}|${v.measureClear}`, items: [], draft: null }
  const addPoint = (kind: MeasureKind, x: number, y: number) => {
    const hit = handle?.worldAt(x, y)
    const index = hit ? view?.planes[hit.tile]?.index : undefined
    if (!handle || !hit || !index) return
    const cur = mine.draft && mine.draft.kind === kind && mine.draft.tile === hit.tile ? mine.draft : { id: ++measureSeq.current, kind, tile: hit.tile, slice: index, points: [] }
    const draft: Measurement = { ...cur, points: [...cur.points, hit.ras] }
    if (draft.points.length < NEEDED[kind]) return setMeasures({ ...mine, draft })
    if (kind === 'roi') {
      const [c, e] = draft.points as [Vec3, Vec3]
      const r = Math.hypot(...([0, 1, 2].map((a) => e[a]! - c[a]!) as [number, number, number]))
      draft.stats = handle.roiStats(hit.tile, c, r)
    }
    setMeasures({ ...mine, items: [...mine.items, draft], draft: null })
  }

  // VW-09 surfaces: fetch meshes (API-25) once requested
  const wantMeshes = !!handle && local.surfaces && !!meshUrl && hasMask && load.phase === 'ready'
  const [meshDone, setMeshDone] = useState<{ key: string; ok: boolean } | null>(null)
  const meshState: MeshState = !wantMeshes || meshDone?.key === loadKey ? (meshDone?.ok === false ? 'error' : 'idle') : 'building'
  useEffect(() => {
    if (!wantMeshes || !handle || !meshUrl) return
    const ac = new AbortController()
    const key = loadKey
    const present = labels.filter((l) => item.labels_present.includes(l.value))
    Promise.all(present.map(async (l) => ({ label: l.value, color: l.color, data: await fetchMesh(meshUrl(l.value), ac.signal) })))
      .then((specs) => handle.setMeshes(specs))
      .then(() => !ac.signal.aborted && setMeshDone({ key, ok: true }))
      .catch(() => !ac.signal.aborted && setMeshDone({ key, ok: false }))
    return () => ac.abort()
  }, [wantMeshes, handle, meshUrl, loadKey, labels, item.labels_present])

  // Tiles: the DOM frames are the layout; the engine draws into their bodies
  const measure = useCallback(() => {
    const c = canvasHost.current
    const g = grid.current
    if (!handle || !c || !g) return
    const origin = c.getBoundingClientRect()
    const tiles: TileRect[] = []
    for (const el of g.querySelectorAll<HTMLElement>('[data-tile]')) {
      const id = el.dataset.tile as ViewportId
      if (id === '3d' && !hasMask) continue
      const r = el.getBoundingClientRect()
      tiles.push({ id, x: r.left - origin.left, y: r.top - origin.top, w: r.width, h: r.height })
    }
    handle.setTiles(tiles)
  }, [handle, hasMask])
  useLayoutEffect(() => {
    measure()
    const el = host.current
    if (!el) return
    const ro = new ResizeObserver(() => measure())
    ro.observe(el)
    return () => ro.disconnect()
  }, [measure, v.layout, v.maximized])
  useEffect(() => handle?.setLayout(v.layout), [handle, v.layout])

  // Space+drag pans (VW-06)
  useEffect(() => {
    if (!active) return
    const down = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !(e.target instanceof HTMLInputElement)) space.current = true
    }
    const up = (e: KeyboardEvent) => {
      if (e.code === 'Space') space.current = false
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [active])

  // ---- pointer interactions ----------------------------------------------------------------

  const local2canvas = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = canvasHost.current?.getBoundingClientRect()
    return r ? [e.clientX - r.left, e.clientY - r.top] : [0, 0]
  }

  const onPointerDown = (tile: ViewportId) => (e: RPointerEvent<HTMLDivElement>) => {
    if (!handle || load.phase !== 'ready') return
    const tool = useViewerSync.getState().tool
    let mode: Drag['mode'] | null = null
    if (e.button === 2) mode = tile === '3d' ? 'zoom' : 'window'
    else if (e.button === 1 || (e.button === 0 && (space.current || tool === 'pan'))) mode = 'pan'
    else if (e.button === 0 && tile !== '3d' && (tool === 'distance' || tool === 'angle' || tool === 'roi')) {
      e.preventDefault()
      addPoint(tool, ...local2canvas(e))
      return
    } else if (e.button === 0) mode = tile === '3d' ? 'orbit' : tool === 'window' ? 'window' : tool === 'zoom' ? 'zoom' : 'pick'
    if (!mode) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    const { ww, wl } = useViewerSync.getState()
    drag.current = { mode, tile, x: e.clientX, y: e.clientY, start: [ww, wl] }
    if (mode === 'pick') handle.pick(...local2canvas(e))
  }

  const onPointerMove = (e: RPointerEvent<HTMLDivElement>) => {
    if (!handle) return
    const [x, y] = local2canvas(e)
    handle.hover(x, y)
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x
    const dy = e.clientY - d.y
    if (d.mode === 'pick') handle.pick(x, y)
    else if (d.mode === 'window') {
      const [ww, wl] = dragWindow(d.start, dx, dy, 1000)
      useViewerSync.getState().setWindow(ww, wl)
    } else if (d.mode === 'pan') {
      handle.pan(d.tile, e.movementX, e.movementY)
    } else if (d.mode === 'zoom') {
      handle.zoom(d.tile, Math.exp(-e.movementY / 150))
    } else handle.orbit(e.movementX * 0.5, e.movementY * 0.5)
  }

  const onPointerUp = () => {
    drag.current = null
  }

  const onWheel = (tile: ViewportId) => (e: RWheelEvent<HTMLDivElement>) => {
    if (!handle || load.phase !== 'ready') return
    if (e.ctrlKey || e.metaKey || tile === '3d') {
      handle.zoom(tile, Math.exp(-e.deltaY / 300))
      return
    }
    // macOS turns Shift+wheel into a horizontal scroll
    const delta = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX
    if (!delta || !isPlane(tile)) return
    handle.step(tile, (delta > 0 ? -1 : 1) * (e.shiftKey ? 10 : 1))
  }

  // Non-passive wheel listener so the page never scrolls under the viewer
  useEffect(() => {
    const el = grid.current
    if (!el) return
    const stop = (e: WheelEvent) => e.preventDefault()
    el.addEventListener('wheel', stop, { passive: false })
    return () => el.removeEventListener('wheel', stop)
  }, [])

  const pct = load.progress?.total ? Math.round((load.progress.loaded / load.progress.total) * 100) : null

  if (!webgl)
    return (
      <div className="error-card" role="alert">
        <strong>{t('vw.noWebgl')}</strong>
      </div>
    )

  return (
    <div ref={host} className="vp-surface">
      <div ref={canvasHost} className="vp-engine-host" />
      {load.phase === 'loading' ? (
        <div className="case-loading" title={pct !== null ? t('vw.loading', { pct }) : t('vw.decoding')}>
          <Progress value={load.progress?.loaded ?? 0} total={load.progress?.total ?? 0} />
        </div>
      ) : null}
      <div ref={grid} className={`vp-grid vp-grid-${v.maximized ? 'one' : v.layout}`} onContextMenu={(e) => e.preventDefault()}>
        {viewports.map((id) => (
          <Viewport
            key={id}
            id={id}
            plane={isPlane(id) ? (view?.planes[id] ?? null) : null}
            hasMask={hasMask}
            labels={labels.filter((l) => item.labels_present.includes(l.value))}
            maximized={v.maximized === id}
            onMaximize={() => v.set({ maximized: v.maximized === id ? null : id })}
            onFit={() => handle?.fitView(id)}
            onGoto={(i) => isPlane(id) && handle?.goto(id as Plane, i)}
            meshState={meshState}
            bodyProps={{
              onPointerDown: onPointerDown(id),
              onPointerMove,
              onPointerUp,
              onPointerCancel: onPointerUp,
              onPointerEnter: () => useViewerLocal.setState({ hovered: id }),
              onPointerLeave: () => {
                useViewerSync.setState({ cursor: null })
                if (useViewerLocal.getState().hovered === id) useViewerLocal.setState({ hovered: null })
              },
              onWheel: onWheel(id),
            }}
          />
        ))}
      </div>
      <MeasureLayer handle={handle} view={view} items={mine.items} draft={mine.draft} />
      {load.phase === 'ready' && active ? <ProbeReadout /> : null}
      {load.maskError ? (
        <div className="vp-notice" role="status">
          <Icon spec={codicon('warning')} />
          {t('vw.maskError')}
        </div>
      ) : null}
      {!loaded ? <div className="vp-veil">{t('vw.unloaded')}</div> : null}
      {load.phase === 'loading' && !load.progress ? <div className="vp-veil">{t('common.loading')}</div> : null}
      {load.phase === 'error' && load.error ? (
        <div className="vp-veil">
          <div className="error-card" role="alert" style={{ maxWidth: 560 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ color: 'var(--error)', display: 'inline-flex' }}>
                <Icon spec={codicon('error')} />
              </span>
              <strong>{t('vw.loadError')}</strong>
              {load.error.status ? <span className="badge mono">{t('vw.errorCode', { status: load.error.status, code: load.error.code ?? '—' })}</span> : null}
            </div>
            <div className="muted">{load.error.message}</div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

/** VW-22 HU probe: the value under the cursor (and its voxel and label) over the viewer */
function ProbeReadout() {
  const { t } = useTranslation()
  const cursor = useViewerSync((s) => s.cursor)
  if (!cursor) return null
  return (
    <div className="vp-probe mono" role="status" aria-label={t('vw.probe')}>
      {t('vw.probeValue', { v: cursor.value })}
      <span className="muted">{t('vw.probeIjk', { ijk: cursor.ijk.join(', ') })}</span>
      {cursor.label ? <span className="muted">{t('vw.probeLabel', { label: cursor.label })}</span> : null}
    </div>
  )
}
