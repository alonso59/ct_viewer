// Mid-slices of the fixture volumes for the mock mode's viewer placeholder (TST-04, TST-11).
// Usage: npm run mock:slices [-- <fixtures dir>]   (default: ../.fixtures/synthetic)
// Writes src/api/mock/slices.json (image + mask slice sets of the first 20 scans, lazy-loaded; the
// others show the empty placeholder, which keeps the committed file below 1 MB).
// Pixel data only; every API answer of the mock is recorded from the backend (`make record-mock`).
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gunzipSync } from 'node:zlib'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(process.argv[2] ?? join(here, '../../.fixtures/synthetic'))
const out = join(here, '../src/api/mock/slices.json')

const expected = JSON.parse(readFileSync(join(root, 'expected.json'), 'utf8'))
const dataDir = join(root, expected.dataset)
const rows = readFileSync(join(dataDir, 'metadata.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))

// Minimal NIfTI-1 reader: dims + voxel data (int16 / uint8 / float32)
function readNifti(path) {
  if (!existsSync(path)) return null
  let buf
  try {
    buf = gunzipSync(readFileSync(path))
  } catch {
    return null
  }
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength)
  const dim = [1, 2, 3].map((i) => dv.getInt16(40 + i * 2, true))
  const datatype = dv.getInt16(70, true)
  const off = Math.round(dv.getFloat32(108, true))
  const n = dim[0] * dim[1] * dim[2]
  const data = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    if (datatype === 4) data[i] = dv.getInt16(off + i * 2, true)
    else if (datatype === 2) data[i] = dv.getUint8(off + i)
    else if (datatype === 16) data[i] = dv.getFloat32(off + i * 4, true)
  }
  return { dim, data }
}

// Mid-slices in radiological display orientation. Row 0 is the top of the image.
function midSlices(vol, Ctor) {
  const [nx, ny, nz] = vol.dim
  const at = (x, y, z) => vol.data[x + nx * (y + ny * z)]
  const cut = (w, h, f) => {
    const a = new Ctor(w * h)
    for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) a[r * w + c] = f(c, r)
    return { w, h, b64: Buffer.from(a.buffer).toString('base64') }
  }
  const [mx, my, mz] = [nx >> 1, ny >> 1, nz >> 1]
  return {
    axial: cut(nx, ny, (c, r) => at(c, ny - 1 - r, mz)),
    coronal: cut(nx, nz, (c, r) => at(c, my, nz - 1 - r)),
    sagittal: cut(ny, nz, (c, r) => at(c, mx, nz - 1 - r)),
  }
}

const MAX_SETS = 20
const slices = {}
for (const row of rows) {
  if (Object.keys(slices).length >= MAX_SETS) break
  const item_id = `${row.case_id}.${row.scan_idx}.complete.-`
  if (slices[item_id]) continue // duplicate identity: the first row wins (IMP-08)
  const rel = row.relative_path ?? row.filename ?? ''
  const segRel = row.seg_path ?? (row.filename ? `seg/${row.filename.replace(/_0000(\.nii(\.gz)?)$/, '$1')}` : '')
  const img = rel ? readNifti(join(dataDir, rel)) : null
  if (!img) continue
  const seg = segRel ? readNifti(join(dataDir, segRel)) : null
  slices[item_id] = { image: midSlices(img, Int16Array), mask: seg && seg.dim.join() === img.dim.join() ? midSlices(seg, Uint8Array) : null }
}
writeFileSync(out, JSON.stringify(slices))
console.log(`mock slices: ${Object.keys(slices).length} slice sets`)
