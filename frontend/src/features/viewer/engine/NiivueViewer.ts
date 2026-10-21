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
import { fitFov, fovOf, linkFov, setFov, zoomed, type Fov } from '../model/fov'
import { PLANE_AXIS, PLANES } from '../model/layouts'
import { DEFAULT_SCENE_3D, project3D } from '../model/scene3d'
import type { CursorReadout, DisplayOptions, LabelStyle, LoadOptions, MeshSpec, Plane, PlaneView, Render3DOptions, RoiStats, TileRect, Unsubscribe, ViewerContext, ViewerHandle, ViewportId, ViewState } from '../model/types'
import { percentileWindow, windowToRange } from '../model/wl'
import { fetchVolume } from './fetchVolume'
import { LoadGate, type Ticket } from './loadGate'
import { SLICE_FRAG, SliceRenderer } from './sliceRenderer'
import { SceneRenderer } from './sceneRenderer'
import { apply, fromGl, invert4, labelArray, niftiBytes, proxyGrid, resampleNearest, texMatrix, toGl, type Mat, type Vec3 } from './volumeMath'

type Typed = Int8Array | Uint8Array | Int16Array | Uint16Array | Int32Array | Uint32Array | Float32Array | Float64Array

/** 3D proxy budget: 256×256×300 for the reference volume */
const PROXY_VOXELS = 24_000_000
/** Wait this long after the last W/L or label change before refreshing the 3D proxy */
const REFRESH_3D_MS = 200
/** Default 3D camera (VW-26 fit, VW-10 reset) */
const AZIMUTH = 110
const ELEVATION = 15

const SLICE: Record<Plane, SLICE_TYPE> = {
  axial: SLICE_TYPE.AXIAL,
  coronal: SLICE_TYPE.CORONAL,
  sagittal: SLICE_TYPE.SAGITTAL,
}
const PLANE_OF: Record<number, Plane> = { [SLICE_TYPE.AXIAL]: 'axial', [SLICE_TYPE.CORONAL]: 'coronal', [SLICE_TYPE.SAGITTAL]: 'sagittal' }

/** Niivue with per-plane 2D pan/zoom (unlinked zoom, VW-06), a 2D slice hook and a post-draw hook */
class TiledNiivue extends Niivue {
  planePan: Partial<Record<Plane, Fov>> = {}
  pan3d: [number, number] = [0, 0]
  render3d: ((mvp: Float32Array, draw: () => void) => void) | null = null
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

  override calculateMvpMatrix(...args: Parameters<Niivue['calculateMvpMatrix']>): ReturnType<Niivue['calculateMvpMatrix']> {
    const matrices = super.calculateMvpMatrix(...args)
    const m = matrices[0]
    // Translate in clip space so volume, meshes and guides move together at any orbit/zoom.
    if (m) for (let col = 0; col < 4; col++) {
      const i = col * 4
      m[i] = m[i]! + this.pan3d[0] * m[i + 3]!
      m[i + 1] = m[i + 1]! + this.pan3d[1] * m[i + 3]!
    }
    return matrices
  }

  override drawImage3D(mvp: Parameters<Niivue['drawImage3D']>[0], azimuth: number, elevation: number): void {
    const draw = () => super.drawImage3D(mvp, azimuth, elevation)
    if (this.render3d) this.render3d(new Float32Array(mvp), draw)
    else draw()
  }

  override drawSceneCore(): string | void {
    // Decorations belong to the frame, before NiiVue finishes/submits its GL commands.
    const r = super.drawSceneCore()
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
  /** RAS voxel size in mm of the rendered volume (slab thickness → texture fraction) */
  private pixRAS: Vec3 = [1, 1, 1]
  private display: DisplayOptions = { invert: false, slab: { mode: 'none', mm: 10 }, interpolation: 'linear', convention: 'radiological' }
  private proxy: NVImage | null = null
  private proxyMask: NVImage | null = null
  private sceneRenderer: SceneRenderer | null = null
  private renderMatrix: Float32Array | null = null
  private render3d = { volume: true, mask: true, surfaces: false, opacity: 1, blend: 1, scene: DEFAULT_SCENE_3D }
  private labels: LabelStyle[] = []
  private overlay = { visible: true, opacity: 1 }
  private tiles: TileRect[] = []
  private linked = false
  private lastPlane: Plane = 'axial'
  /** Last 2D view zoomed or panned: its field of view is copied when zoom gets linked (VW-06) */
  private lastFov: Plane = 'axial'
  private ww = 400
  private wl = 50
  private cursorCbs = new Set<(r: CursorReadout | null) => void>()
  private viewCbs = new Set<(s: ViewState) => void>()
  private dirty = { volume: false, draw: false }
  private raf = 0
  private timer3d = 0
  private meshes = new Map<number, NVMesh>()
  private gate = new LoadGate()
  private meshGate = new LoadGate()
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
      meshThicknessOn2D: 0, // Mask surfaces belong only to 3D; slices keep their label overlay.
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
    this.nv.afterDraw = () => { this.drawSceneGuides(); this.emitView() }
    this.nv.render3d = (mvp, draw) => this.drawVolume3D(mvp, draw)
    this.nv.beforeSlice = (program) => this.slices?.prepare(program)
    this.ready = this.nv.attachToCanvas(canvas).then(() => {
      if (this.disposed) return
      this.slices = new SliceRenderer(this.nv.gl)
      this.sceneRenderer = new SceneRenderer(this.nv.gl, canvas)
      this.nv.setCustomSliceShader(SLICE_FRAG)
    })
  }

  // ---- loading ------------------------------------------------------------------------------

  async load(item: ItemRecord, opts: LoadOptions): Promise<void> {
    // AUD-A5-13: after every await, stop unless this is still the newest load (VW-14/15)
    const ticket = this.gate.begin(opts.signal)
    performance.mark('rw:load-start')
    await this.ready
    if (!ticket.check()) return
    this.maskError = null
    const maskBytes = opts.maskUrl ? fetchVolume(opts.maskUrl, undefined, opts.signal) : null
    // A failed mask must not fail the image; it is reported through `maskError`
    maskBytes?.catch(() => undefined)
    const { bytes } = await fetchVolume(opts.imageUrl, opts.onProgress, opts.signal)
    if (!ticket.check()) return
    const img = await parse(bytes, `${item.item_id}.nii`)
    if (!ticket.check()) return
    this.clearVolumes()
    const f = full(img)
    this.image = f
    const d = img.dimsRAS
    this.dimsRAS = d ? [d[1] ?? 1, d[2] ?? 1, d[3] ?? 1] : f.dims
    const px = img.pixDimsRAS
    this.pixRAS = px ? [px[1] ?? 1, px[2] ?? 1, px[3] ?? 1] : [1, 1, 1]

    // 3D proxy: NiiVue renders this one; the full volume goes to the slice shader
    const grid = proxyGrid(f.dims, f.affine, PROXY_VOXELS)
    const proxy = grid.factor === 1 ? img : await parse(niftiBytes(resampleNearest(f.data, f.dims, grid.dims), grid.dims, grid.affine, { slope: f.slope, inter: f.inter }), `${item.item_id}_3d.nii`)
    if (!ticket.check()) return
    const [lo, hi] = windowToRange(this.ww, this.wl)
    proxy.cal_min = lo
    proxy.cal_max = hi
    this.proxy = proxy
    this.slices!.setImage({ data: f.data, dims: f.dims, slope: f.slope, inter: f.inter })
    this.slices!.setWindow(lo, hi)
    this.applyDisplay()
    this.nv.addVolume(proxy)
    this.updateMatrices()
    this.resetView()
    performance.mark('rw:first-slice')
    opts.onImage?.()

    if (!maskBytes) return
    try {
      const mb = await maskBytes
      if (!ticket.check()) return
      await this.loadMask(item, mb, f, ticket)
    } catch (e) {
      if (opts.signal?.aborted) throw e
      this.maskError = e instanceof Error ? e.message : String(e)
    }
  }

  private async loadMask(item: ItemRecord, { bytes }: { bytes: ArrayBuffer }, image: Full, ticket: Ticket): Promise<void> {
    const stale = () => !ticket.live() || this.image !== image
    if (stale()) return
    const m = await parse(bytes, `${item.item_id}_mask.nii`)
    const mf = full(m)
    const labels = labelArray(mf.data)
    if (!labels) throw new Error('The segmentation does not contain integer labels')
    if (stale()) return
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
      if (stale()) return
      pm.hdr!.intent_code = 1002 // exact-index label shader
      pm.setColormapLabel(niivueLut(this.labels, lutWidth(this.labels, max)))
      pm.opacity = this.overlay.visible ? 1 : 0
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
    this.nv.pan3d = [0, 0]
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
    this.styleMeshes()
    const pm = this.proxyMask
    if (pm) {
      pm.setColormapLabel(niivueLut(this.labels, width))
      pm.opacity = this.overlay.visible ? 1 : 0
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

  setRender(p: Render3DOptions): void {
    this.render3d = { ...this.render3d, ...p }
    this.nv.opts.isOrientCube = this.render3d.scene.orientationCube
    this.nv.opts.fontColor = this.render3d.scene.background === 'white' ? [0, 0, 0, 1] : [1, 1, 1, 1]
    this.styleMeshes()
    this.schedule('draw')
  }

  /** Blank only the 3D background sampler: image geometry and the 2D textures stay intact. */
  private drawVolume3D(mvp: Float32Array, draw: () => void) {
    this.renderMatrix = mvp
    const nv = this.nv
    const gl = nv.gl
    const renderer = this.sceneRenderer
    if (!renderer || !nv.renderShader) return draw()
    renderer.background(this.render3d.scene.background)
    const shader = nv.renderShader
    shader.use(gl)
    const hideCT = !this.render3d.volume || this.render3d.opacity === 0
    const surfaceReady = this.render3d.surfaces && this.meshes.size > 0
    gl.activeTexture(gl.TEXTURE15)
    gl.bindTexture(gl.TEXTURE_3D, renderer.emptyVolume)
    gl.activeTexture(gl.TEXTURE0)
    // NiiVue's uniform parser omits the first name in `uniform sampler3D volume, overlay`.
    const volumeSampler = gl.getUniformLocation(shader.program, 'volume')
    if (!volumeSampler) return draw()
    const volumeUnit = gl.getUniform(shader.program, volumeSampler) as number
    gl.uniform1i(volumeSampler, hideCT ? 15 : volumeUnit)
    gl.uniform1f(shader.uniforms.backOpacity!, this.render3d.opacity)
    gl.uniform1f(shader.uniforms.overlays!, this.render3d.mask && !surfaceReady ? nv.volumes.length - 1 : 0)
    gl.uniform1f(shader.uniforms.renderOverlayBlend!, this.render3d.blend)
    try { draw() } finally {
      shader.use(gl)
      gl.uniform1i(volumeSampler, volumeUnit)
      gl.uniform1f(shader.uniforms.backOpacity!, this.proxy?.opacity ?? 1)
      gl.uniform1f(shader.uniforms.overlays!, nv.volumes.length - 1)
    }
    const fracToMM = nv.back?.frac2mm
    if (fracToMM) for (const plane of PLANES) {
      if (this.render3d.scene.planes[plane] === 'slice') this.slices?.drawPlane(mvp, new Float32Array(fracToMM), PLANE_AXIS[plane], this.crosshair[PLANE_AXIS[plane]])
    }
  }

  private styleMeshes() {
    for (const [value, mesh] of this.meshes) {
      const label = this.labels.find((l) => l.value === value)
      mesh.visible = this.render3d.mask && this.render3d.surfaces && this.overlay.visible && (label?.visible ?? true)
      mesh.opacity = this.render3d.blend
    }
  }

  private drawSceneGuides() {
    const tile = this.tiles.find((t) => t.id === '3d')
    const matrix = this.renderMatrix
    const fracToMM = this.nv.back?.frac2mm
    if (!tile || !matrix || !fracToMM || !this.sceneRenderer) return
    const gl = this.nv.gl
    const k = this.dpr()
    gl.viewport(tile.x * k, gl.canvas.height - (tile.y + tile.h) * k, tile.w * k, tile.h * k)
    this.sceneRenderer.guides(matrix, fromGl(fracToMM), this.crosshair, this.render3d.scene)
    gl.viewport(0, 0, gl.canvas.width, gl.canvas.height)
    if (!this.render3d.scene.axisLabels) return
    const names = [['L', 'R'], ['P', 'A'], ['I', 'S']]
    for (const axis of [0, 1, 2] as const) for (const side of [0, 1] as const) {
      const frac: Vec3 = [0.5, 0.5, 0.5]; frac[axis] = side === 0 ? -0.035 : 1.035
      const mm = this.nv.frac2mm(frac, 0, true)
      const point = project3D(matrix, [mm[0]!, mm[1]!, mm[2]!], tile.w * k, tile.h * k)
      if (point && point[0] > 12 * k && point[0] < (tile.w - 20) * k && point[1] > 12 * k && point[1] < (tile.h - 12) * k) {
        this.nv.drawText([tile.x * k + point[0], tile.y * k + point[1]], names[axis]![side]!, 0.8, this.nv.opts.fontColor)
      }
    }
  }

  async setMeshes(specs: MeshSpec[]): Promise<void> {
    // AUD-A5-13: a newer call, or a newer image, drops the meshes this call is still reading
    const ticket = this.meshGate.begin()
    const image = this.gate.current
    const live = () => ticket.live() && this.gate.current === image
    await this.ready
    if (!live()) return
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
      if (!live() || this.meshes.has(s.label)) return
      this.meshes.set(s.label, mesh)
      this.nv.addMesh(mesh)
    }
    this.styleMeshes()
    this.schedule('draw')
  }

  // ---- display options (VW-22/23/25) -----------------------------------------------------------

  setDisplay(p: Partial<DisplayOptions>): void {
    this.display = { ...this.display, ...p, slab: { ...this.display.slab, ...p.slab } }
    this.applyDisplay()
  }

  private applyDisplay() {
    const s = this.slices
    if (!s) return
    const d = this.display
    s.setInvert(d.invert)
    s.setInterpolation(d.interpolation === 'linear')
    const mode = { none: 0, mip: 1, minip: 2, avg: 3 }[d.slab.mode]
    const half = [0, 1, 2].map((a) => d.slab.mm / 2 / Math.max(1e-6, this.dimsRAS[a as 0 | 1 | 2] * this.pixRAS[a as 0 | 1 | 2])) as Vec3
    s.setSlab(mode, half)
    const radiological = d.convention === 'radiological'
    if (this.nv.opts.isRadiologicalConvention !== radiological) this.nv.opts.isRadiologicalConvention = radiological
    this.schedule('draw')
  }

  // ---- measurements (VW-17) -----------------------------------------------------------------

  worldAt(x: number, y: number): { tile: Plane; ras: Vec3 } | null {
    const t = this.tileAt(x, y)
    if (!t || t.id === '3d') return null
    const f = this.fracAt(x, y)
    if (!f) return null
    const mm = this.nv.frac2mm(f, 0, true)
    return { tile: t.id, ras: [mm[0] ?? 0, mm[1] ?? 0, mm[2] ?? 0] }
  }

  canvasAt(ras: Vec3, tile: Plane): [number, number] | null {
    if (!this.image || !this.tiles.some((t) => t.id === tile)) return null
    const frac = [...this.nv.mm2frac(ras, 0, true)] as Vec3
    const hit = this.nv.frac2canvasPosWithTile(frac, SLICE[tile])
    if (!hit) return null
    const k = this.dpr()
    return [hit.pos[0]! / k, hit.pos[1]! / k]
  }

  roiStats(tile: Plane, center: Vec3, radiusMm: number): RoiStats | null {
    const v = this.image
    if (!v?.inv || radiusMm <= 0) return null
    const r = Math.min(radiusMm, 150)
    const axis = PLANE_AXIS[tile]
    // Voxel size per native axis (column norms of the affine)
    const size = [0, 1, 2].map((c) => Math.hypot(v.affine[0]![c]!, v.affine[1]![c]!, v.affine[2]![c]!) || 1)
    const c = apply(v.inv, center)
    const lo = [0, 1, 2].map((a) => Math.max(0, Math.floor(c[a]! - r / size[a]! - 1)))
    const hi = [0, 1, 2].map((a) => Math.min(v.dims[a]! - 1, Math.ceil(c[a]! + r / size[a]! + 1)))
    const halfSlice = this.pixRAS[axis] / 2
    let n = 0
    let sum = 0
    let sq = 0
    let min = Infinity
    let max = -Infinity
    for (let k = lo[2]!; k <= hi[2]!; k++)
      for (let j = lo[1]!; j <= hi[1]!; j++)
        for (let i = lo[0]!; i <= hi[0]!; i++) {
          const p = apply(v.affine, [i, j, k])
          if (Math.abs(p[axis] - center[axis]) > halfSlice) continue
          const d2 = [0, 1, 2].reduce((s, a) => (a === axis ? s : s + (p[a]! - center[a]!) ** 2), 0)
          if (d2 > r * r) continue
          const val = sample(v, [i, j, k])
          if (val === null) continue
          n++
          sum += val
          sq += val * val
          if (val < min) min = val
          if (val > max) max = val
        }
    if (!n) return null
    const mean = sum / n
    return { n, mean, sd: Math.sqrt(Math.max(0, sq / n - mean * mean)), min, max, areaMm2: Math.PI * r * r }
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
    if (!this.image || !Number.isFinite(dx) || !Number.isFinite(dy)) return
    if (tile === '3d') {
      const rect = this.tiles.find((t) => t.id === '3d')
      if (!rect || rect.w <= 0 || rect.h <= 0) return
      this.nv.pan3d[0] += 2 * dx / rect.w
      this.nv.pan3d[1] -= 2 * dy / rect.h
      this.schedule('draw')
      return
    }
    // Screen px → mm with the tile's field of view (recorded by NiiVue on the last draw)
    const s = this.nv.screenSlices.find((ss) => ss.axCorSag === SLICE[tile])
    if (!s) return
    const k = this.dpr()
    const fov = s.fovMM as number[]
    const ltwh = s.leftTopWidthHeight as number[]
    const mmPerPx = ((fov[0] ?? 1) / (ltwh[2] || 1)) * k
    const mmPerPy = ((fov[1] ?? 1) / (ltwh[3] || 1)) * k
    const p = this.panOf(tile)
    // The image follows the pointer: NiiVue's pan offset grows to the right on screen along the
    // horizontal world axis (R for axial/coronal, A for sagittal) and upwards along the vertical one
    // (A for axial, S otherwise). NiiVue applies the radiological/neurological flip itself (VW-25).
    const h = tile === 'sagittal' ? 1 : 0
    const v = tile === 'axial' ? 1 : 2
    p[h] += dx * mmPerPx
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
    this.setPan(tile, zoomed(this.panOf(tile), factor))
  }

  private panOf(tile: Plane): Fov {
    return fovOf(this.nv.planePan, tile)
  }

  private setPan(tile: Plane, p: Fov) {
    this.lastFov = tile
    setFov(this.nv.planePan, tile, p, this.linked)
    this.schedule('draw')
  }

  setLinkedZoom(linked: boolean): void {
    this.linked = linked
    if (linked) {
      linkFov(this.nv.planePan, this.lastFov)
      this.schedule('draw')
    }
  }

  orbit(dAz: number, dEl: number): void {
    const s = this.nv.scene
    this.nv.setRenderAzimuthElevation(s.renderAzimuth + dAz, Math.max(-90, Math.min(90, s.renderElevation + dEl)))
  }

  /** VW-26: fit one view to its tile; the slice, crosshair and W/L stay as they are */
  fitView(tile: ViewportId): void {
    if (tile === '3d') {
      this.nv.pan3d = [0, 0]
      this.nv.scene.volScaleMultiplier = 1
      this.nv.setRenderAzimuthElevation(AZIMUTH, ELEVATION)
    } else fitFov(this.nv.planePan, tile, this.linked)
    this.schedule('draw')
  }

  /** VW-10: fit every view and centre the crosshair */
  resetView(): void {
    for (const pl of PLANES) this.fitView(pl)
    this.fitView('3d')
    if (this.image) this.setFrac([0.5, 0.5, 0.5])
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
    this.gate.close()
    this.meshGate.close()
    cancelAnimationFrame(this.raf)
    clearTimeout(this.timer3d)
    this.cursorCbs.clear()
    this.viewCbs.clear()
    try {
      this.clearVolumes()
      this.slices?.dispose()
      this.sceneRenderer?.dispose()
      this.nv.cleanup()
    } catch {
      // context may already be gone
    }
    // Release the GPU memory now rather than at garbage collection (VW-14)
    this.nv.gl?.getExtension('WEBGL_lose_context')?.loseContext()
    this.canvas.remove()
  }
}
