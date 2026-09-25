// Engine-neutral viewer contract (VIEWER.md §Wrapper contract). Nothing here imports NiiVue.
import type { ItemRecord } from '../../../api'
import type { CursorReadout, LayoutId, ViewportId } from '../../../state'

export type { CursorReadout, LayoutId, ViewportId }
export type Plane = Exclude<ViewportId, '3d'>
export type Vec3 = [number, number, number]
export type Unsubscribe = () => void

/** Curation context attached to CUR events (`context.viewer`, VW-16) */
export interface ViewerContext {
  axis: Plane
  /** 1-based slice index along `axis`, as shown in the viewport header */
  slice: number
  ww: number
  wl: number
}

export interface LabelStyle {
  value: number
  color: string
  visible: boolean
  /** 0..1 fill opacity */
  opacity: number
  /** Outline only: interior hidden, boundary voxels drawn (VW-07) */
  outline: boolean
}

/** A viewport body in CSS pixels, relative to the engine canvas */
export interface TileRect {
  id: ViewportId
  x: number
  y: number
  w: number
  h: number
}

/** Per-plane view state reported after every redraw (headers, sliders, crosshair lines) */
export interface PlaneView {
  index: number
  total: number
  /** Crosshair in tile CSS px (null when outside the tile) */
  cross: [number, number] | null
  zoom: number
}

export interface ViewState {
  planes: Partial<Record<Plane, PlaneView>>
  ras: Vec3
}

export interface LoadProgress {
  loaded: number
  total: number | null
}

export interface LoadOptions {
  imageUrl: string
  maskUrl?: string
  onProgress?: (p: LoadProgress) => void
  onImage?: () => void
  signal?: AbortSignal
}

/** VW-23: slab projection over a thickness in mm (2D tiles) */
export type SlabMode = 'none' | 'mip' | 'minip' | 'avg'

/** VW-22/23/25 display options of the 2D tiles */
export interface DisplayOptions {
  invert: boolean
  slab: { mode: SlabMode; mm: number }
  interpolation: 'linear' | 'nearest'
  convention: 'radiological' | 'neurological'
}

/** VW-17: in-plane circular ROI statistics in physical units (HU for CT) */
export interface RoiStats {
  n: number
  mean: number
  sd: number
  min: number
  max: number
  areaMm2: number
}

export interface MeshSpec {
  label: number
  color: string
  /** gzip MZ3 bytes (API-25) */
  data: ArrayBuffer
}

export interface ViewerHandle {
  /** Resolves once image and mask are in; `onImage` fires at the first rendered slice (VW-13) */
  load(item: ItemRecord, opts: LoadOptions): Promise<void>
  /** Set when the mask failed to load; the image stays usable (VW-12) */
  readonly maskError: string | null
  setLayout(id: LayoutId): void
  setWindow(ww: number, wl: number): void
  setLabel(value: number, p: { visible?: boolean; opacity?: number; outline?: boolean; color?: string }): void
  setCrosshair(ras: Vec3): void
  onCursor(cb: (r: CursorReadout | null) => void): Unsubscribe
  snapshot(): ViewerContext
  dispose(): void

  // Extensions used by the case editor (engine-neutral as well)
  setTiles(tiles: TileRect[]): void
  setLabels(labels: LabelStyle[]): void
  setOverlay(p: { visible?: boolean; opacity?: number }): void
  setCrosshairVisible(v: boolean): void
  setLinkedZoom(linked: boolean): void
  setRender(p: { volume?: boolean; labels?: boolean; blend?: number }): void
  setMeshes(meshes: MeshSpec[]): Promise<void>
  /** Wheel / slider: move `plane` by `delta` slices, or to 1-based `index` */
  step(plane: Plane, delta: number): void
  goto(plane: Plane, index: number): void
  /** Pointer interactions, in CSS px relative to the canvas */
  pick(x: number, y: number): void
  hover(x: number, y: number): void
  pan(tile: ViewportId, dx: number, dy: number): void
  zoom(tile: ViewportId, factor: number): void
  orbit(dAzimuth: number, dElevation: number): void
  /** VW-26: fit one view to its tile (2D: zoom 100 %, no pan; 3D: default camera) */
  fitView(tile: ViewportId): void
  /** VW-10: fit every view, crosshair to the volume centre */
  resetView(): void
  /** Default window for the loaded image (CT preset or 1st–99th percentile, VW-05) */
  defaultWindow(): [number, number]
  onView(cb: (s: ViewState) => void): Unsubscribe
  screenshot(): Promise<Blob | null>
  /** VW-22/23/25: invert, slab MIP/MinIP/average, interpolation, orientation convention */
  setDisplay(p: Partial<DisplayOptions>): void
  /** VW-17: the RAS mm point under a canvas position on a 2D tile */
  worldAt(x: number, y: number): { tile: Plane; ras: Vec3 } | null
  /** VW-17: canvas CSS px of a RAS point on a 2D tile (null when that tile is not shown) */
  canvasAt(ras: Vec3, tile: Plane): [number, number] | null
  /** VW-17: statistics of the image voxels within `radiusMm` of `center` on the tile's slice */
  roiStats(tile: Plane, center: Vec3, radiusMm: number): RoiStats | null
  /** Frame counter and cost of the last frame in ms; `sync` waits for the GPU (TST-09 bench) */
  readonly stats: { frames: number; lastFrameMs: number; sync: boolean }
}
