// Engine math: texture mappings, 3D proxy grid, NIfTI writer (no WebGL needed)
import { apply, fromGl, invert4, labelArray, mul4, niftiBytes, proxyGrid, resampleNearest, texMatrix, toGl, type Mat, type Vec3 } from './volumeMath'

const I4: Mat = [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
]
const LPS: Mat = [
  [-0.78, 0, 0, 199],
  [0, -0.78, 0, 199],
  [0, 0, 0.8, -240],
  [0, 0, 0, 1],
]

/** NiiVue-style frac2mm: fraction 0..1 spans voxel edges (−0.5 .. n−0.5) */
const frac2mm = (A: Mat, n: Vec3): Mat =>
  mul4(A, [
    [n[0], 0, 0, -0.5],
    [0, n[1], 0, -0.5],
    [0, 0, n[2], -0.5],
    [0, 0, 0, 1],
  ])

const close = (a: number[], b: number[], eps = 1e-6) => a.forEach((x, i) => expect(Math.abs(x - (b[i] ?? NaN))).toBeLessThan(eps))

test('invert4 and gl round trips', () => {
  const inv = invert4(LPS)!
  close(mul4(LPS, inv).flat(), I4.flat())
  expect(invert4([[0, 0, 0, 0], ...I4.slice(1)])).toBeNull()
  close(fromGl(toGl(LPS)).flat(), LPS.flat())
})

test('texMatrix maps a fraction to the same voxel in native texture space', () => {
  const n: Vec3 = [4, 5, 6]
  const M = texMatrix(frac2mm(LPS, n), LPS, n)!
  // voxel (1,2,3) centre: frac = (i + 0.5) / n; texcoord = (i + 0.5) / n too
  const f: Vec3 = [1.5 / 4, 2.5 / 5, 3.5 / 6]
  close(apply(M, f), f)
})

test('proxy grid keeps the physical extent (voxel edges line up)', () => {
  const n: Vec3 = [512, 512, 601]
  const g = proxyGrid(n, LPS, 24_000_000)
  expect(g.factor).toBe(2)
  expect(g.dims).toEqual([256, 256, 301])
  // Edges of the full grid and of the proxy land on the same world points
  const edge = (A: Mat, d: Vec3): Vec3[] => [apply(A, [-0.5, -0.5, -0.5]), apply(A, [d[0] - 0.5, d[1] - 0.5, d[2] - 0.5])]
  const [a0, a1] = edge(LPS, n)
  const [b0, b1] = edge(g.affine, g.dims)
  close(a0!, b0!, 1e-4)
  close(a1!, b1!, 1e-4)
  // Small volumes are used as they are
  expect(proxyGrid([64, 64, 48], LPS, 24_000_000).factor).toBe(1)
})

test('resampleNearest keeps labels and type', () => {
  const src = Uint8Array.from({ length: 4 * 4 * 2 }, (_, i) => (i % 4 < 2 ? 1 : 2))
  const out = resampleNearest(src, [4, 4, 2], [2, 2, 1])
  expect(out).toBeInstanceOf(Uint8Array)
  expect([...out]).toEqual([1, 2, 1, 2])
})

test('niftiBytes writes a readable NIfTI-1 header', () => {
  const data = Int16Array.from([1, 2, 3, 4, 5, 6, 7, 8])
  const buf = niftiBytes(data, [2, 2, 2], LPS, { slope: 2, inter: -1, intent: 1002 })
  const v = new DataView(buf)
  expect(v.getInt32(0, true)).toBe(348)
  expect(v.getInt16(42, true)).toBe(2)
  expect(v.getInt16(68, true)).toBe(1002)
  expect(v.getInt16(70, true)).toBe(4) // DT_INT16
  expect(v.getFloat32(112, true)).toBe(2)
  expect(v.getFloat32(80, true)).toBeCloseTo(0.78, 5)
  expect(v.getInt16(254, true)).toBe(1)
  expect(v.getFloat32(280, true)).toBeCloseTo(-0.78, 5)
  expect([...new Int16Array(buf, 352)]).toEqual([...data])
})

test('labelArray picks the smallest integer type and rejects non-labels', () => {
  expect(labelArray(Int16Array.from([0, 1, 3]))).toBeInstanceOf(Uint8Array)
  expect(labelArray(Int16Array.from([0, 300]))).toBeInstanceOf(Uint16Array)
  expect(labelArray(Float32Array.from([0, 1.5]))).toBeNull()
  expect(labelArray(Int16Array.from([-1]))).toBeNull()
})
