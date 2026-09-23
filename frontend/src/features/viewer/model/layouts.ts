// Layouts (VW-01) and plane conventions (VW-04). The CSS grid in viewer.css draws the frames;
// the engine reads each viewport body's rect, so the DOM is the single source of tile geometry.
import type { LayoutId, Plane, ViewportId } from './types'

export const LAYOUT_VIEWPORTS: Record<LayoutId, ViewportId[]> = {
  'four-up': ['axial', 'sagittal', 'coronal', '3d'],
  conventional: ['axial', 'sagittal', 'coronal', '3d'],
  'three-mpr': ['axial', 'sagittal', 'coronal'],
  'one-up-axial': ['axial'],
  'one-up-sagittal': ['sagittal'],
  'one-up-coronal': ['coronal'],
  'one-up-3d': ['3d'],
}

export const LAYOUT_IDS = Object.keys(LAYOUT_VIEWPORTS) as LayoutId[]
export const isLayoutId = (s: string | null | undefined): s is LayoutId => !!s && s in LAYOUT_VIEWPORTS

export const PLANES: Plane[] = ['axial', 'sagittal', 'coronal']
export const isPlane = (id: ViewportId): id is Plane => id !== '3d'

/** RAS axis each plane steps along: axial = S (z), coronal = A (y), sagittal = R (x) */
export const PLANE_AXIS: Record<Plane, 0 | 1 | 2> = { sagittal: 0, coronal: 1, axial: 2 }

/** Planes whose lines cross each 2D view: [vertical line, horizontal line] (3D Slicer) */
export const CROSS: Record<Plane, [Plane, Plane]> = {
  axial: ['sagittal', 'coronal'],
  coronal: ['sagittal', 'axial'],
  sagittal: ['coronal', 'axial'],
}

/** Edge letters (left, right, top, bottom): radiological convention, sagittal nose left (Slicer) */
export const ORIENTATION: Record<Plane, [string, string, string, string]> = {
  axial: ['R', 'L', 'A', 'P'],
  coronal: ['R', 'L', 'S', 'I'],
  sagittal: ['A', 'P', 'S', 'I'],
}

/** Viewports shown for a layout, honouring a maximized viewport (VW-02) */
export function visibleViewports(layout: LayoutId, maximized: ViewportId | null, has3d = true): ViewportId[] {
  if (maximized) return [maximized]
  const vps = LAYOUT_VIEWPORTS[layout]
  return has3d ? vps : vps.filter((v) => v !== '3d' || vps.length === 1)
}
