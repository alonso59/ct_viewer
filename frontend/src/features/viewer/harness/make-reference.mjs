// TST-09 reference volume (NFR.md): abdominal-CT-like phantom, 512×512×600 int16 .nii.gz plus a
// uint8 label mask (1 kidney, 2 tumor, 3 cyst). Deterministic; written under .fixtures/reference/.
// Usage (from frontend/): node src/features/viewer/harness/make-reference.mjs [--nz 600]
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(here, '../../../../../.fixtures/reference')
const arg = (k, d) => {
  const i = process.argv.indexOf(k)
  return i > 0 ? Number(process.argv[i + 1]) : d
}
const NX = 512
const NY = 512
const NZ = arg('--nz', 600)
const SP = [0.78, 0.78, 0.8]

/** NIfTI-1 header (348 bytes + 4 extension bytes) with an LPS-flipped sform, as dcm2niix writes */
function header(datatype, bitpix, intent) {
  const b = Buffer.alloc(352)
  b.writeInt32LE(348, 0)
  const dims = [3, NX, NY, NZ, 1, 1, 1, 1]
  dims.forEach((d, i) => b.writeInt16LE(d, 40 + 2 * i))
  b.writeInt16LE(intent, 68)
  b.writeInt16LE(datatype, 70)
  b.writeInt16LE(bitpix, 72)
  const pix = [1, SP[0], SP[1], SP[2], 1, 1, 1, 1]
  pix.forEach((p, i) => b.writeFloatLE(p, 76 + 4 * i))
  b.writeFloatLE(352, 108) // vox_offset
  b.writeFloatLE(1, 112) // scl_slope
  b.writeFloatLE(0, 116) // scl_inter
  b.writeUInt8(2, 123) // xyzt_units: mm
  b.writeInt16LE(0, 252) // qform_code
  b.writeInt16LE(1, 254) // sform_code (scanner)
  const ox = ((NX - 1) * SP[0]) / 2
  const oy = ((NY - 1) * SP[1]) / 2
  const oz = -((NZ - 1) * SP[2]) / 2
  const rows = [
    [-SP[0], 0, 0, ox],
    [0, -SP[1], 0, oy],
    [0, 0, SP[2], oz],
  ]
  rows.flat().forEach((v, i) => b.writeFloatLE(v, 280 + 4 * i))
  b.write('n+1\0', 344, 'latin1')
  return b
}

// Deterministic PRNG (mulberry32) + Box-Muller noise
let seed = 0x5eed
function rand() {
  seed = (seed + 0x6d2b79f5) | 0
  let t = seed
  t = Math.imul(t ^ (t >>> 15), t | 1)
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296
}
const noise = new Float32Array(1 << 16)
for (let i = 0; i < noise.length; i += 2) {
  const r = Math.sqrt(-2 * Math.log(rand() + 1e-12))
  const a = 2 * Math.PI * rand()
  noise[i] = r * Math.cos(a)
  noise[i + 1] = r * Math.sin(a)
}

const img = new Int16Array(NX * NY * NZ)
const lab = new Uint8Array(NX * NY * NZ)
const cx = NX / 2
const cy = NY / 2
const ell = (x, y, z, e) => ((x - e[0]) / e[3]) ** 2 + ((y - e[1]) / e[4]) ** 2 + ((z - e[2]) / e[5]) ** 2
const zc = NZ / 2
const kidneys = [
  [cx - 95, cy + 40, zc, 34, 48, 70],
  [cx + 95, cy + 40, zc + 10, 34, 48, 70],
]
const tumor = [cx - 110, cy + 30, zc + 25, 18, 18, 18]
const cyst = [cx + 80, cy + 55, zc - 20, 12, 12, 12]
let n = 0
for (let z = 0; z < NZ; z++) {
  const taper = 1 - 0.15 * Math.abs(z - zc) / zc
  for (let y = 0; y < NY; y++)
    for (let x = 0; x < NX; x++, n++) {
      const body = ((x - cx) / (220 * taper)) ** 2 + ((y - cy) / (160 * taper)) ** 2
      let hu = -1000
      let sd = 8
      let l = 0
      if (body <= 1) {
        hu = body > 0.9 ? -100 : 40 // fat rim, soft tissue
        sd = 18
        const spine = ((x - cx) / 28) ** 2 + ((y - (cy + 110)) / 26) ** 2
        if (spine <= 1) hu = spine > 0.6 ? 900 : 300
        const liver = ell(x, y, z, [cx - 80, cy - 40, zc + 120, 110, 80, 140])
        if (liver <= 1) hu = 60
        for (const k of kidneys) {
          const d = ell(x, y, z, k)
          if (d <= 1) {
            hu = d > 0.7 ? 180 : 140 // cortex / medulla
            l = 1
          }
        }
        if (ell(x, y, z, tumor) <= 1) {
          hu = 90
          l = 2
        }
        if (ell(x, y, z, cyst) <= 1) {
          hu = 8
          l = 3
        }
      } else if (y > cy + 175) hu = -300 // table
      img[n] = Math.round(hu + sd * noise[(n * 7 + z) & 0xffff])
      lab[n] = l
    }
}

mkdirSync(out, { recursive: true })
const write = (name, hdr, data) => {
  const raw = Buffer.concat([hdr, Buffer.from(data.buffer, data.byteOffset, data.byteLength)])
  const gz = gzipSync(raw, { level: 6 })
  writeFileSync(resolve(out, name), gz)
  console.log(`${name}: ${(gz.length / 1e6).toFixed(1)} MB (raw ${(raw.length / 1e6).toFixed(0)} MB)`)
}
write('reference_ct.nii.gz', header(4, 16, 0), img)
write('reference_seg.nii.gz', header(2, 8, 0), lab)
