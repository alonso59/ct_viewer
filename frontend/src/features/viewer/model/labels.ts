// Label rendering (VW-07, P3 spike 2).
//
// Decision: NiiVue's own label colormap cannot do this in 2D (its label shader makes every visible
// label fully opaque with one layer-wide opacity, and its outline is 3D). The 2D slices therefore
// use a custom LUT texture read by the engine's slice shader: row 0 = colour + per-label opacity
// (0 = hidden), row 1 = outline flag; the outline is the in-plane boundary, as in 3D Slicer.
// NiiVue's label colormap is still used for the 3D tile, where only visibility matters.
import type { LabelStyle } from './types'

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h.slice(0, 6)
  const n = Number.parseInt(full, 16)
  if (Number.isNaN(n)) return [255, 255, 255]
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

const clamp01 = (x: number) => Math.max(0, Math.min(1, x))

/** 2D LUT rows (width × 2 RGBA8) for labels 0..width-1 */
export function lutRows(labels: LabelStyle[], width: number): Uint8Array {
  const rows = new Uint8Array(width * 2 * 4)
  for (const l of labels) {
    if (l.value <= 0 || l.value >= width || !l.visible) continue
    const [r, g, b] = hexToRgb(l.color)
    const i = l.value * 4
    rows[i] = r
    rows[i + 1] = g
    rows[i + 2] = b
    rows[i + 3] = Math.round(clamp01(l.opacity) * 255)
    rows[(width + l.value) * 4] = l.outline ? 255 : 0
  }
  return rows
}

/** LUT width covering every value in the mask and the label map */
export const lutWidth = (labels: LabelStyle[], maxValue: number) => Math.max(2, maxValue + 1, ...labels.map((l) => l.value + 1))

export interface LabelLut {
  R: number[]
  G: number[]
  B: number[]
  A: number[]
  I: number[]
}

/** NiiVue label colormap for the 3D tile: visible labels opaque, hidden ones transparent */
export function niivueLut(labels: LabelStyle[], width: number): LabelLut {
  const lut: LabelLut = { R: [], G: [], B: [], A: [], I: [] }
  for (let i = 0; i < width; i++) {
    const l = labels.find((x) => x.value === i)
    const [r, g, b] = l ? hexToRgb(l.color) : [0, 0, 0]
    lut.R.push(r)
    lut.G.push(g)
    lut.B.push(b)
    lut.A.push(l?.visible && i > 0 ? 255 : 0)
    lut.I.push(i)
  }
  return lut
}
