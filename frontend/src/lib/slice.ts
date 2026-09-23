// CPU slice rendering for P0.5 placeholders and thumbnails: W/L + label overlay (fill or outline).
// P3 replaces viewport rendering with NiiVue (GPU); thumbnails come from IMP-12 in P2.

export interface SliceRender {
  w: number
  h: number
  image: Int16Array
  mask?: Uint8Array | null
  ww: number
  wl: number
  /** label value → [r, g, b, alpha 0..1]; missing = hidden */
  labels?: Map<number, [number, number, number, number]>
  outline?: boolean
}

export function hexToRgb(hex: string): [number, number, number] {
  const v = parseInt(hex.replace('#', ''), 16)
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255]
}

export function renderSlice(ctx: CanvasRenderingContext2D, r: SliceRender) {
  const { w, h, image, mask, ww, wl, labels, outline } = r
  const out = ctx.createImageData(w, h)
  const lo = wl - ww / 2
  for (let i = 0; i < w * h; i++) {
    const g = Math.max(0, Math.min(255, (((image[i] ?? 0) - lo) / ww) * 255))
    let cr = g
    let cg = g
    let cb = g
    const lab = mask?.[i] ?? 0
    const color = lab ? labels?.get(lab) : undefined
    if (color) {
      const x = i % w
      const y = (i - x) / w
      const edge =
        x === 0 || y === 0 || x === w - 1 || y === h - 1 ||
        mask?.[i - 1] !== lab || mask?.[i + 1] !== lab || mask?.[i - w] !== lab || mask?.[i + w] !== lab
      // Outline mode draws only the boundary at full strength; fill mode tints and strengthens the edge
      const a = outline ? (edge ? 1 : 0) : edge ? Math.min(1, color[3] * 3.5) : color[3]
      cr = cr * (1 - a) + color[0] * a
      cg = cg * (1 - a) + color[1] * a
      cb = cb * (1 - a) + color[2] * a
    }
    out.data[i * 4] = cr
    out.data[i * 4 + 1] = cg
    out.data[i * 4 + 2] = cb
    out.data[i * 4 + 3] = 255
  }
  ctx.putImageData(out, 0, 0)
}
