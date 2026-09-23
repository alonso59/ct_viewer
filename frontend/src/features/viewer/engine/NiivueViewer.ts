// NiiVue implementation of ViewerHandle (ADR-0003). The only module that imports NiiVue.
//
// P3 spike 1 (one instance vs four): ONE Niivue instance per case tab draws every viewport into a
// single canvas through `setCustomLayout`; the DOM frames (headers, sliders, crosshair lines) sit
// on top and their body rects become the tiles. Four instances would hold four copies of the volume.
// NiiVue's own mouse/keyboard handling is off (`interactive: false`); the case editor drives it.
//
// Rendering split (TST-09 on the reference volume): NiiVue re-uploads and re-composites the whole
// volume for every contrast change (≈ 0.5 s at 512×512×600), so
//   · 2D tiles: the engine's slice shader (sliceRenderer.ts) reads full-resolution textures that are
//     uploaded once; W/L and label styling are uniforms.
//   · 3D tile: NiiVue volume-renders a proxy (≤ PROXY_VOXELS, same physical extent) that is
//     refreshed after a W/L drag settles, plus the API-25 meshes.
import { NVImage, NVMesh, Niivue, SLICE_TYPE } from '@niivue/niivue'

import type { ItemRecord } from '../../../api'
import { hexToRgb, lutRows, lutWidth, niivueLut } from '../model/labels'
import { PLANE_AXIS, PLANES } from '../model/layouts'
import type { CursorReadout, LabelStyle, LoadOptions, MeshSpec, Plane, PlaneView, TileRect, Unsubscribe, ViewerContext, ViewerHandle, ViewportId, ViewState } from '../model/types'
import { percentileWindow, windowToRange } from '../model/wl'
import { fetchVolume } from './fetchVolume'
import { SLICE_FRAG, SliceRenderer } from './sliceRenderer'
import { apply, fromGl, invert4, labelArray, niftiBytes, proxyGrid, resampleNearest, texMatrix, toGl, type Mat, type Vec3 } from './volumeMath'

type Vec4 = [number, number, number, number]
type Typed = Int8Array | Uint8Array | Int16Array | Uint16Array | Int32Array | Uint32Array | Float32Array | Float64Array

/** 3D proxy budget: 256×256×300 for the reference volume */
const PROXY_VOXELS = 24_000_000
/** Wait this long after the last W/L or label change before refreshing the 3D proxy */
const REFRESH_3D_MS = 200

const SLICE: Record<Plane, SLICE_TYPE> = {
  axial: SLICE_TYPE.AXIAL,
  coronal: SLICE_TYPE.CORONAL,
  sagittal: SLICE_TYPE.SAGITTAL,
}
const PLANE_OF: Record<number, Plane> = { [SLICE_TYPE.AXIAL]: 'axial', [SLICE_TYPE.CORONAL]: 'coronal', [SLICE_TYPE.SAGITTAL]: 'sagittal' }

/** Niivue with per-plane 2D pan/zoom (unlinked zoom, VW-06), a 2D slice hook and a post-draw hook */
class TiledNiivue extends Niivue {
  planePan: Partial<Record<Plane, Vec4>> = {}
  showVolume3D = true
  beforeSlice: ((program: WebGLProgram) => void) | null = null
  afterDraw: (() => void) | null = null

  override draw2D(ltwh: number[], axCorSag: SLICE_TYPE, customMM?: number, imageWH?: number[]): void {
    const program = this.customSliceShader?.program
    if (program) this.beforeSlice?.(program)
    const plane = PLANE_OF[axCorSag]
    const own = plane ? this.planePan[plane] : undefined
    if (!own) return super.draw2D(ltwh, axCorSag, customMM, imageWH)
    const scene = this.scene
    const saved = scene.pan2Dxyzmm
    scene.pan2Dxyzmm = own as unknown as typeof saved
    try {
      super.draw2D(ltwh, axCorSag, customMM, imageWH)
    } finally {
      scene.pan2Dxyzmm = saved
    }
  }

  override drawImage3D(mvp: Parameters<Niivue['drawImage3D']>[0], azimuth: number, elevation: number): void {
    if (this.showVolume3D) super.drawImage3D(mvp, azimuth, elevation)
  }

  override drawScene(): string | void {
    const r = super.drawScene()
    this.afterDraw?.()
    return r
  }
}

/** A full-resolution volume kept on the CPU for readouts (the GPU copy lives in SliceRenderer) */
interface Full {
  data: Typed
  dims: Vec3
  affine: Mat
  inv: Mat | null
  slope: number
  inter: number
}

async function parse(bytes: ArrayBuffer, name: string): Promise<NVImage> {
  return NVImage.loadFromUrl({ url: name, name, buffer: bytes, colormap: 'gray', trustCalMinMax: false })
}

function full(img: NVImage): Full {
  const hdr = img.hdr!
  const affine = (hdr.affine as unknown as Mat).map((r) => [...r])
  const slope = hdr.scl_slope && Number.isFinite(hdr.scl_slope) ? hdr.scl_slope : 1
  const inter = Number.isFinite(hdr.scl_inter) ? hdr.scl_inter : 0
  return { data: img.img as unknown as Typed, dims: [hdr.dims[1] ?? 1, hdr.dims[2] ?? 1, hdr.dims[3] ?? 1], affine, inv: invert4(affine), slope, inter }
}

function sample(v: Full, ijk: Vec3): number | null {
  const [nx, ny, nz] = v.dims
  const [i, j, k] = ijk
  if (i < 0 || j < 0 || k < 0 || i >= nx || j >= ny || k >= nz) return null
  return (v.data[i + j * nx + k * nx * ny] ?? 0) * v.slope + v.inter
}

export class NiivueViewer implements ViewerHandle {
  private nv: TiledNiivue
  private canvas: HTMLCanvasElement
  private slices: SliceRenderer | null = null
  private image: Full | null = null
  private mask: Full | null = null
  private maskMax = 0
  /** RAS dims of the full-resolution image (slice stepping, indices) */
  private dimsRAS: Vec3 = [1, 1, 1]
  private proxy: NVImage | null = null
  private proxyMask: NVImage | null = null
  private labels: LabelStyle[] = []
  private overlay = { visible: true, opacity: 1 }
  private tiles: TileRect[] = []
  private linked = true
  private lastPlane: Plane = 'axial'
  private ww = 400
  private wl = 50
  private cursorCbs = new Set<(r: CursorReadout | null) => void>()
  private viewCbs = new Set<(s: ViewState) => void>()
  private dirty = { volume: false, draw: false }
  private raf = 0
  private timer3d = 0
  private meshes = new Map<number, NVMesh>()
  private disposed = false
  private ready: Promise<unknown>
  readonly stats = { frames: 0, lastFrameMs: 0, sync: false }
  maskError: string | null = null

  /** Each instance owns its canvas: a context lost on dispose can never be reused (VW-14) */
  constructor(host: HTMLElement) {
    const canvas = document.createElement('canvas')
    canvas.className = 'vp-engine'
    canvas.setAttribute('aria-hidden', 'true')
    host.prepend(canvas)
    this.canvas = canvas
    this.nv = new TiledNiivue({
      interactive: false,
      dragAndDropEnabled: false,
      isResizeCanvas: true,
      backColor: [0, 0, 0, 1],
      crosshairWidth: 0,
      show3Dcrosshair: false,
      isColorbar: false,
      isRuler: false,
      isOrientCube: false,
      isOrientationTextVisible: false,
      isRadiologicalConvention: true,
      sagittalNoseLeft: true,
      isSliceMM: false,
      multiplanarShowRender: 1,
      tileMargin: 0,
      logLevel: 'error',
      loadingText: '',
    })
    this.nv.afterDraw = () => this.emitView()
    this.nv.beforeSlice = (program) => this.slices?.prepare(program)
    this.ready = this.nv.attachToCanvas(canvas).then(() => {
      if (this.disposed) return
      this.slices = new SliceRenderer(this.nv.gl)
      this.nv.setCustomSliceShader(SLICE_FRAG)
    })
  }

  // ---- loading ------------------------------------------------------------------------------

  async load(item: ItemRecord, opts: LoadOptions): Promise<void> {
    performance.mark('rw:load-start')
    await this.ready
    this.maskError = null
    const maskBytes = opts.maskUrl ? fetchVolume(opts.maskUrl, undefined, opts.signal) : null
    // A failed mask must not fail the image; it is reported through `maskError`
    maskBytes?.catch(() => undefined)
    const { bytes } = await fetchVolume(opts.imageUrl, opts.onProgress, opts.signal)
    if (this.disposed) return
    const img = await parse(bytes, `${item.item_id}.nii`)
    if (this.disposed) return
    this.clearVolumes()
    const f = full(img)
    this.image = f
    const d = img.dimsRAS
    this.dimsRAS = d ? [d[1] ?? 1, d[2] ?? 1, d[3] ?? 1] : f.dims

    // 3D proxy: NiiVue renders this one; the full volume goes to the slice shader
    const grid = proxyGrid(f.dims, f.affine, PROXY_VOXELS)
    const proxy = grid.factor === 1 ? img : await parse(niftiBytes(resampleNearest(f.data, f.dims, grid.dims), grid.dims, grid.affine, { slope: f.slope, inter: f.inter }), `${item.item_id}_3d.nii`)
    if (this.disposed) return
    const [lo, hi] = windowToRange(this.ww, this.wl)
    proxy.cal_min = lo
    proxy.cal_max = hi
    this.proxy = proxy
    this.slices!.setImage({ data: f.data, dims: f.dims, slope: f.slope, inter: f.inter })
    this.slices!.setWindow(lo, hi)
    this.nv.addVolume(proxy)
    this.updateMatrices()
    this.resetView()
    performance.mark('rw:first-slice')
    opts.onImage?.()

    if (!maskBytes) return
    try {
      await this.loadMask(item, await maskBytes, f)
    } catch (e) {
      if (opts.signal?.aborted) throw e
      this.maskError = e instanceof Error ? e.message : String(e)
    }
  }

  private async loadMask(item: ItemRecord, { bytes }: { bytes: ArrayBuffer }, image: Full): Promise<void> {
    if (this.disposed || this.image !== image) return
    const m = await parse(bytes, `${item.item_id}_mask.nii`)
    const mf = full(m)
    const labels = labelArray(mf.data)
    if (!labels) throw new Error('The segmentation does not contain integer labels')
    if (this.disposed || this.image !== image) return
    let max = 0
    for (let i = 0; i < labels.length; i++) if (labels[i]! > max) max = labels[i]!
    this.maskMax = max
    this.mask = { ...mf, data: labels, slope: 1, inter: 0 }
    this.slices!.setLabel(labels, mf.dims)

    // 3D label render on a proxy of the mask's own grid
    const grid = proxyGrid(mf.dims, mf.affine, PROXY_VOXELS)
    const u8 = labels instanceof Uint8Array ? labels : null
    if (u8) {
      const data = grid.factor === 1 ? u8 : resampleNearest(u8, mf.dims, grid.dims)
      const pm = await parse(niftiBytes(data, grid.dims, grid.affine, { intent: 1002 }), `${item.item_id}_mask3d.nii`)
      if (this.disposed || this.image !== image) return
      pm.hdr!.intent_code = 1002 // exact-index label shader
      pm.setColormapLabel(niivueLut(this.labels, lutWidth(this.labels, max)))
      pm.opacity = this.overlay.visible ? this.overlay.opacity : 0
      this.proxyMask = pm
      this.nv.addVolume(pm)
    }
    this.updateMatrices()
    this.refreshLut(false)
    performance.mark('rw:mask')
  }

  /** texPos (NiiVue's RAS fraction of the proxy) → native texture coords of each full volume */
  private updateMatrices() {
    const back = this.nv.volumes[0]
    if (!back?.frac2mm || !this.image || !this.slices) return
    const f2m = fromGl(back.frac2mm)
    const img = texMatrix(f2m, this.image.affine, this.image.dims)
    const lab = this.mask ? texMatrix(f2m, this.mask.affine, this.mask.dims) : null
    if (!img) return
    const [nx, ny, nz] = this.dimsRAS
    this.slices.setMatrices(toGl(img), lab ? toGl(lab) : null, [1 / nx, 1 / ny, 1 / nz])
  }

  private clearVolumes() {
    for (const v of [...this.nv.volumes]) this.nv.removeVolume(v)
    for (const m of this.meshes.values()) this.nv.removeMesh(m)
    this.meshes.clear()
    this.slices?.setLabel(null, [1, 1, 1])
    this.image = null
    this.mask = null
    this.proxy = null
    this.proxyMask = null
  }

  // ---- scheduling ---------------------------------------------------------------------------

  private schedule(kind: 'volume' | 'draw') {
    this.dirty[kind] = true
    if (this.raf) return
    this.raf = requestAnimationFrame(() => {
      this.raf = 0
      if (this.disposed) return
      const t0 = performance.now()
      if (this.dirty.volume) this.nv.updateGLVolume()
      else if (this.dirty.draw) this.nv.drawScene()
      this.dirty = { volume: false, draw: false }
      // Bench only: wait for the GPU so lastFrameMs is the real frame cost (TST-09)
      if (this.stats.sync) this.nv.gl.readPixels(0, 0, 1, 1, this.nv.gl.RGBA, this.nv.gl.UNSIGNED_BYTE, new Uint8Array(4))
      this.stats.frames++
      this.stats.lastFrameMs = performance.now() - t0
    })
  }

  /** The 3D proxy follows 2D changes once they settle (only when a 3D tile is shown) */
  private schedule3d() {
    clearTimeout(this.timer3d)
    if (!this.tiles.some((t) => t.id === '3d')) return
    this.timer3d = window.setTimeout(() => this.schedule('volume'), REFRESH_3D_MS)
  }

  // ---- layout / tiles -----------------------------------------------------------------------

  /** Tiles come from the DOM frames (setTiles); the layout id only matters to the caller */
  setLayout(): void {}

  setTiles(tiles: TileRect[]): void {
    const had3d = this.tiles.some((t) => t.id === '3d')
    this.tiles = tiles
    const cw = this.canvas.clientWidth
    const ch = this.canvas.clientHeight
    if (!cw || !ch) return
    this.nv.resizeListener()
    const layout = tiles.map((t) => ({
      sliceType: t.id === '3d' ? SLICE_TYPE.RENDER : SLICE[t.id],
      position: [t.x / cw, t.y / ch, t.w / cw, t.h / ch] as [number, number, number, number],
    }))
    if (layout.length) this.nv.setCustomLayout(layout)
    // A 3D tile that just appeared may show a stale proxy
    this.schedule(this.proxy && !had3d && tiles.some((t) => t.id === '3d') ? 'volume' : 'draw')
  }

  // ---- window / labels / overlay ------------------------------------------------------------

  setWindow(ww: number, wl: number): void {
    this.ww = ww
    this.wl = wl
    const [lo, hi] = windowToRange(ww, wl)
    this.slices?.setWindow(lo, hi)
    if (!this.proxy) return
    this.proxy.cal_min = lo
    this.proxy.cal_max = hi
    this.schedule('draw')
    this.schedule3d()
  }

  defaultWindow(): [number, number] {
    const v = this.image
    if (!v) return [this.ww, this.wl]
    return percentileWindow(v.data, v.slope, v.inter)
  }

  setLabels(labels: LabelStyle[]): void {
    this.labels = labels.map((l) => ({ ...l }))
    this.refreshLut(true)
  }

  setLabel(value: number, p: { visible?: boolean; opacity?: number; outline?: boolean; color?: string }): void {
    const l = this.labels.find((x) => x.value === value)
    if (l) Object.assign(l, Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined)))
    else this.labels.push({ value, color: p.color ?? '#ffffff', visible: p.visible ?? true, opacity: p.opacity ?? 0.5, outline: p.outline ?? false })
    this.refreshLut(true)
  }

  private refreshLut(defer3d: boolean) {
    const width = lutWidth(this.labels, this.maskMax)
    this.slices?.setLut(lutRows(this.labels, width), width)
    this.slices?.setOverlay(this.overlay.visible ? this.overlay.opacity : 0)
    for (const [label, mesh] of this.meshes) mesh.visible = !!this.labels.find((x) => x.value === label)?.visible && this.overlay.visible
    const pm = this.proxyMask
    if (pm) {
      pm.setColormapLabel(niivueLut(this.labels, width))
      pm.opacity = this.overlay.visible ? this.overlay.opacity : 0
    }
    this.schedule('draw')
    if (pm) {
      if (defer3d) this.schedule3d()
      else this.schedule('volume')
    }
  }

  setOverlay(p: { visible?: boolean; opacity?: number }): void {
    Object.assign(this.overlay, Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined)))
    this.refreshLut(true)
  }

  setCrosshairVisible(): void {
    // Crosshair lines are drawn by the DOM overlay (VW-04 per-plane colours); nothing to do here
  }

  setRender(p: { volume?: boolean; labels?: boolean; blend?: number }): void {
    if (p.volume !== undefined) this.nv.showVolume3D = p.volume
    if (p.blend !== undefined) this.nv.opts.renderOverlayBlend = p.blend
    if (p.labels !== undefined) for (const mesh of this.meshes.values()) mesh.visible = p.labels
    this.schedule('draw')
    if (p.blend !== undefined) this.schedule3d()
  }

  async setMeshes(specs: MeshSpec[]): Promise<void> {
    await this.ready
    const want = new Set(specs.map((s) => s.label))
    for (const [label, mesh] of this.meshes)
      if (!want.has(label)) {
        this.nv.removeMesh(mesh)
        this.meshes.delete(label)
      }
    for (const s of specs) {
      if (this.meshes.has(s.label)) continue
      const [r, g, b] = hexToRgb(s.color)
      const mesh = await NVMesh.readMesh(s.data.slice(0), `label${s.label}.mz3`, this.nv.gl, 1, new Uint8Array([r, g, b, 255]))
      if (this.disposed) return
      mesh.visible = this.labels.find((l) => l.value === s.label)?.visible ?? true
      this.meshes.set(s.label, mesh)
      this.nv.addMesh(mesh)
    }
    this.schedule('draw')
  }

  // ---- navigation (full-resolution voxel centres) -------------------------------------------

  private get crosshair(): Vec3 {
    return [...this.nv.scene.crosshairPos] as Vec3
  }

  /** 0-based full-resolution RAS voxel index of a fraction along `axis` */
  private indexOf(frac: number, axis: 0 | 1 | 2) {
    const n = this.dimsRAS[axis]
    return Math.max(0, Math.min(n - 1, Math.floor(frac * n)))
  }

  private centre(index: number, axis: 0 | 1 | 2) {
    const n = this.dimsRAS[axis]
    return (Math.max(0, Math.min(n - 1, index)) + 0.5) / n
  }

  /** Snap to voxel centres so slices never blend two planes */
  private setFrac(frac: Vec3) {
    const snapped = frac.map((f, a) => this.centre(this.indexOf(f, a as 0 | 1 | 2), a as 0 | 1 | 2)) as Vec3
    this.nv.scene.crosshairPos = snapped as unknown as typeof this.nv.scene.crosshairPos
    this.schedule('draw')
  }

  setCrosshair(ras: Vec3): void {
    if (!this.image) return
    this.setFrac([...this.nv.mm2frac(ras, 0, true)] as Vec3)
  }

  step(plane: Plane, delta: number): void {
    if (!this.image) return
    this.lastPlane = plane
    const f = this.crosshair
    const a = PLANE_AXIS[plane]
    f[a] = this.centre(this.indexOf(f[a], a) + delta, a)
    this.setFrac(f)
  }

  goto(plane: Plane, index: number): void {
    if (!this.image) return
    this.lastPlane = plane
    const f = this.crosshair
    const a = PLANE_AXIS[plane]
    f[a] = this.centre(Math.round(index) - 1, a)
    this.setFrac(f)
  }

  private dpr() {
    return this.canvas.clientWidth ? this.canvas.width / this.canvas.clientWidth : 1
  }

  private fracAt(x: number, y: number): Vec3 | null {
    if (!this.image) return null
    const k = this.dpr()
    const f = [...this.nv.canvasPos2frac([x * k, y * k])] as Vec3
    return f[0] < 0 || f[1] < 0 || f[2] < 0 || f[0] > 1 || f[1] > 1 || f[2] > 1 ? null : f
  }

  private tileAt(x: number, y: number): TileRect | undefined {
    return this.tiles.find((t) => x >= t.x && y >= t.y && x < t.x + t.w && y < t.y + t.h)
  }

  pick(x: number, y: number): void {
    const t = this.tileAt(x, y)
    if (!t || t.id === '3d') return
    this.lastPlane = t.id
    const f = this.fracAt(x, y)
    if (f) this.setFrac(f)
  }

  hover(x: number, y: number): void {
    const t = this.tileAt(x, y)
    const f = t && t.id !== '3d' ? this.fracAt(x, y) : null
    const r = f ? this.readout(f) : null
    for (const cb of this.cursorCbs) cb(r)
  }

  private readout(frac: Vec3): CursorReadout | null {
    const v = this.image
    if (!v?.inv) return null
    const mm4 = this.nv.frac2mm(frac, 0, true)
    const ras: Vec3 = [mm4[0] ?? 0, mm4[1] ?? 0, mm4[2] ?? 0]
    const ijk = apply(v.inv, ras).map(Math.round) as Vec3
    const value = sample(v, ijk)
    if (value === null) return null
    const m = this.mask
    const label = m?.inv ? (sample(m, apply(m.inv, ras).map(Math.round) as Vec3) ?? 0) : 0
    return { ijk, ras: ras.map((c) => Math.round(c * 10) / 10) as Vec3, value: Math.round(value * 100) / 100, label }
  }

  pan(tile: ViewportId, dx: number, dy: number): void {
    if (tile === '3d' || !this.image) return
    // Screen px → mm with the tile's field of view (recorded by NiiVue on the last draw)
    const s = this.nv.screenSlices.find((ss) => ss.axCorSag === SLICE[tile])
    if (!s) return
    const k = this.dpr()
    const fov = s.fovMM as number[]
    const ltwh = s.leftTopWidthHeight as number[]
    const mmPerPx = ((fov[0] ?? 1) / (ltwh[2] || 1)) * k
    const mmPerPy = ((fov[1] ?? 1) / (ltwh[3] || 1)) * k
    const p = this.panOf(tile)
    // World axes behind the screen axes. Radiological convention + sagittal nose left means screen
    // right is −R (axial, coronal) or −A (sagittal), and screen down is −A (axial) or −S.
    const h = tile === 'sagittal' ? 1 : 0
    const v = tile === 'axial' ? 1 : 2
    p[h] -= dx * mmPerPx
    p[v] -= dy * mmPerPy
    this.setPan(tile, p)
  }

  zoom(tile: ViewportId, factor: number): void {
    if (tile === '3d') {
      const s = this.nv.scene
      s.volScaleMultiplier = Math.max(0.3, Math.min(4, s.volScaleMultiplier * factor))
      this.schedule('draw')
      return
    }
    const p = this.panOf(tile)
    p[3] = Math.max(0.5, Math.min(16, p[3] * factor))
    this.setPan(tile, p)
  }

  private panOf(tile: Plane): Vec4 {
    const own = this.nv.planePan[tile]
    return own ? [...own] : [0, 0, 0, 1]
  }

  private setPan(tile: Plane, p: Vec4) {
    if (this.linked) for (const pl of PLANES) this.nv.planePan[pl] = [...p]
    else this.nv.planePan[tile] = p
    this.schedule('draw')
  }

  setLinkedZoom(linked: boolean): void {
    this.linked = linked
    if (linked) {
      const p = this.panOf(this.lastPlane)
      for (const pl of PLANES) this.nv.planePan[pl] = [...p]
      this.schedule('draw')
    }
  }

  orbit(dAz: number, dEl: number): void {
    const s = this.nv.scene
    this.nv.setRenderAzimuthElevation(s.renderAzimuth + dAz, Math.max(-90, Math.min(90, s.renderElevation + dEl)))
  }

  resetView(): void {
    for (const pl of PLANES) this.nv.planePan[pl] = [0, 0, 0, 1]
    this.nv.scene.volScaleMultiplier = 1
    this.nv.setRenderAzimuthElevation(110, 15)
    if (this.image) this.setFrac([0.5, 0.5, 0.5])
    else this.schedule('draw')
  }

  // ---- reporting ----------------------------------------------------------------------------

  private emitView() {
    if (!this.viewCbs.size || !this.image) return
    const frac = this.crosshair
    const k = this.dpr()
    const planes: ViewState['planes'] = {}
    for (const t of this.tiles) {
      if (t.id === '3d') continue
      const axis = PLANE_AXIS[t.id]
      const hit = this.nv.frac2canvasPosWithTile(frac, SLICE[t.id])
      const cross: [number, number] | null = hit ? [hit.pos[0]! / k - t.x, hit.pos[1]! / k - t.y] : null
      const view: PlaneView = { index: this.indexOf(frac[axis], axis) + 1, total: this.dimsRAS[axis], cross, zoom: this.panOf(t.id)[3] }
      planes[t.id] = view
    }
    const mm = this.nv.frac2mm(frac, 0, true)
    const s: ViewState = { planes, ras: [mm[0] ?? 0, mm[1] ?? 0, mm[2] ?? 0] }
    for (const cb of this.viewCbs) cb(s)
  }

  onCursor(cb: (r: CursorReadout | null) => void): Unsubscribe {
    this.cursorCbs.add(cb)
    return () => this.cursorCbs.delete(cb)
  }

  onView(cb: (s: ViewState) => void): Unsubscribe {
    this.viewCbs.add(cb)
    this.emitView()
    return () => this.viewCbs.delete(cb)
  }

  snapshot(): ViewerContext {
    const axis = this.lastPlane
    const a = PLANE_AXIS[axis]
    return { axis, slice: this.image ? this.indexOf(this.crosshair[a], a) + 1 : 0, ww: this.ww, wl: this.wl }
  }

  async screenshot(): Promise<Blob | null> {
    this.nv.drawScene() // the drawing buffer is only valid right after a draw
    return new Promise((resolve) => this.canvas.toBlob(resolve, 'image/png'))
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    cancelAnimationFrame(this.raf)
    clearTimeout(this.timer3d)
    this.cursorCbs.clear()
    this.viewCbs.clear()
    try {
      this.clearVolumes()
      this.slices?.dispose()
      this.nv.cleanup()
    } catch {
      // context may already be gone
    }
    // Release the GPU memory now rather than at garbage collection (VW-14)
    this.nv.gl?.getExtension('WEBGL_lose_context')?.loseContext()
    this.canvas.remove()
  }
}
