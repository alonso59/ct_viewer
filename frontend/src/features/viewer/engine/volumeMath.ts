// Pure volume helpers for the engine: affines, texture mappings, 3D proxy volumes. No NiiVue here.

export type Mat = number[][]
export type Vec3 = [number, number, number]
type Typed = Int8Array | Uint8Array | Int16Array | Uint16Array | Int32Array | Uint32Array | Float32Array | Float64Array

export function invert4(m: Mat): Mat | null {
  // Gauss-Jordan on a 4×4 (affines are tiny; clarity over speed)
  const a = m.map((row, i) => [...row.slice(0, 4), ...[0, 1, 2, 3].map((j) => (i === j ? 1 : 0))])
  for (let c = 0; c < 4; c++) {
    let p = c
    for (let r = c + 1; r < 4; r++) if (Math.abs(a[r]![c]!) > Math.abs(a[p]![c]!)) p = r
    if (Math.abs(a[p]![c]!) < 1e-12) return null
    ;[a[c], a[p]] = [a[p]!, a[c]!]
    const d = a[c]![c]!
    for (let j = 0; j < 8; j++) a[c]![j]! /= d
    for (let r = 0; r < 4; r++) {
      if (r === c) continue
      const f = a[r]![c]!
      for (let j = 0; j < 8; j++) a[r]![j]! -= f * a[c]![j]!
    }
  }
  return a.map((row) => row.slice(4))
}

export function mul4(a: Mat, b: Mat): Mat {
  return [0, 1, 2, 3].map((i) => [0, 1, 2, 3].map((j) => [0, 1, 2, 3].reduce((s, k) => s + a[i]![k]! * b[k]![j]!, 0)))
}

export const apply = (m: Mat, v: Vec3): Vec3 => [0, 1, 2].map((i) => m[i]![0]! * v[0] + m[i]![1]! * v[1] + m[i]![2]! * v[2] + m[i]![3]!) as Vec3

/** gl-matrix (column-major) → rows */
export const fromGl = (m: ArrayLike<number>): Mat => [0, 1, 2, 3].map((r) => [0, 1, 2, 3].map((c) => m[c * 4 + r] ?? 0))
/** rows → column-major Float32Array */
export const toGl = (m: Mat): Float32Array => Float32Array.from([0, 1, 2, 3].flatMap((c) => [0, 1, 2, 3].map((r) => m[r]![c]!)))

/**
 * RAS texture fraction (of the volume NiiVue renders) → native texture coordinates of a volume
 * with `affine` and `dims`: t = (A⁻¹ · frac2mm · p + 0.5) / n
 */
export function texMatrix(frac2mm: Mat, affine: Mat, dims: Vec3): Mat | null {
  const inv = invert4(affine)
  if (!inv) return null
  const s: Mat = [
    [1 / dims[0], 0, 0, 0.5 / dims[0]],
    [0, 1 / dims[1], 0, 0.5 / dims[1]],
    [0, 0, 1 / dims[2], 0.5 / dims[2]],
    [0, 0, 0, 1],
  ]
  return mul4(s, mul4(inv, frac2mm))
}

/** Proxy grid for the 3D tile: ≤ `maxVoxels`, same physical extent (voxel edges line up) */
export function proxyGrid(dims: Vec3, affine: Mat, maxVoxels: number): { dims: Vec3; affine: Mat; factor: number } {
  const n = dims[0] * dims[1] * dims[2]
  const factor = n <= maxVoxels ? 1 : Math.ceil(Math.cbrt(n / maxVoxels))
  if (factor === 1) return { dims, affine, factor }
  const m = dims.map((d) => Math.max(1, Math.ceil(d / factor))) as Vec3
  // New voxel k spans old [(k)·f − 0.5, (k+1)·f − 0.5] with f = n/m: centre at (k + 0.5)·f − 0.5
  const f = dims.map((d, i) => d / m[i]!)
  const scale: Mat = [
    [f[0]!, 0, 0, 0.5 * f[0]! - 0.5],
    [0, f[1]!, 0, 0.5 * f[1]! - 0.5],
    [0, 0, f[2]!, 0.5 * f[2]! - 0.5],
    [0, 0, 0, 1],
  ]
  return { dims: m, affine: mul4(affine, scale), factor }
}

/** Nearest-neighbour resample onto a proxy grid (labels stay labels) */
export function resampleNearest<T extends Typed>(data: T, dims: Vec3, to: Vec3): T {
  const Ctor = data.constructor as new (n: number) => T
  const out = new Ctor(to[0] * to[1] * to[2])
  const fx = dims[0] / to[0]
  const fy = dims[1] / to[1]
  const fz = dims[2] / to[2]
  const ix = Array.from({ length: to[0] }, (_, i) => Math.min(dims[0] - 1, Math.floor((i + 0.5) * fx)))
  let o = 0
  for (let z = 0; z < to[2]; z++) {
    const sz = Math.min(dims[2] - 1, Math.floor((z + 0.5) * fz)) * dims[0] * dims[1]
    for (let y = 0; y < to[1]; y++) {
      const sy = sz + Math.min(dims[1] - 1, Math.floor((y + 0.5) * fy)) * dims[0]
      for (let x = 0; x < to[0]; x++) out[o++] = data[sy + ix[x]!]!
    }
  }
  return out
}

const DATATYPE: [new (n: number) => Typed, number, number][] = [
  [Uint8Array, 2, 8],
  [Int16Array, 4, 16],
  [Int32Array, 8, 32],
  [Float32Array, 16, 32],
  [Float64Array, 64, 64],
  [Int8Array, 256, 8],
  [Uint16Array, 512, 16],
  [Uint32Array, 768, 32],
]

/** Minimal NIfTI-1 (.nii) bytes: sform = affine, scl = slope/inter, intent as given */
export function niftiBytes(data: Typed, dims: Vec3, affine: Mat, opts: { slope?: number; inter?: number; intent?: number } = {}): ArrayBuffer {
  const entry = DATATYPE.find(([C]) => data instanceof C)
  if (!entry) throw new Error('unsupported datatype')
  const [, code, bits] = entry
  const buf = new ArrayBuffer(352 + data.byteLength)
  const v = new DataView(buf)
  v.setInt32(0, 348, true)
  ;[3, dims[0], dims[1], dims[2], 1, 1, 1, 1].forEach((d, i) => v.setInt16(40 + 2 * i, d, true))
  v.setInt16(68, opts.intent ?? 0, true)
  v.setInt16(70, code, true)
  v.setInt16(72, bits, true)
  const col = (j: number) => Math.hypot(affine[0]![j]!, affine[1]![j]!, affine[2]![j]!)
  ;[1, col(0), col(1), col(2), 1, 1, 1, 1].forEach((p, i) => v.setFloat32(76 + 4 * i, p, true))
  v.setFloat32(108, 352, true)
  v.setFloat32(112, opts.slope ?? 1, true)
  v.setFloat32(116, opts.inter ?? 0, true)
  v.setUint8(123, 2)
  v.setInt16(254, 1, true) // sform_code
  for (let r = 0; r < 3; r++) for (let c = 0; c < 4; c++) v.setFloat32(280 + 16 * r + 4 * c, affine[r]![c]!, true)
  ;[0x6e, 0x2b, 0x31, 0].forEach((b, i) => v.setUint8(344 + i, b))
  new Uint8Array(buf, 352).set(new Uint8Array(data.buffer, data.byteOffset, data.byteLength))
  return buf
}

/** Integer label volume as the smallest unsigned integer array (null if not integral / negative) */
export function labelArray(data: ArrayLike<number>): Uint8Array | Uint16Array | null {
  let max = 0
  for (let i = 0; i < data.length; i++) {
    const x = data[i] ?? 0
    if (x < 0 || x !== Math.floor(x) || x > 65535) return null
    if (x > max) max = x
  }
  if (data instanceof Uint8Array) return data
  if (max <= 255) return Uint8Array.from(data)
  return data instanceof Uint16Array ? data : Uint16Array.from(data)
}
