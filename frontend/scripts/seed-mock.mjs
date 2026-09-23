// Builds the P0.5 mock API seed from `make fixtures` output (TST-11).
// Usage: npm run mock:seed [-- <fixtures dir>]   (default: ../.fixtures/synthetic)
// Writes src/api/mock/seed.json (index, warnings, one radiomics run) and
// src/api/mock/slices.json (mid-slices per complete item; lazy-loaded by the viewer placeholder).
// Feature values: first-order and shape are computed from the fixture voxels; texture values are
// derived stand-ins. The fixture spheres are near-identical, so a deterministic per-item spread
// (size, intensity, texture) and two defect effects are added so the dashboard wireframe has shape:
// affine_mismatch → mask samples the wrong tissue; ambiguous_phase → different enhancement.
// Design data only: nothing here is IBSI-validated (P5 replaces it with real engine output).
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gunzipSync } from 'node:zlib'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(process.argv[2] ?? join(here, '../../.fixtures/synthetic'))
const outDir = join(here, '../src/api/mock')

const expected = JSON.parse(readFileSync(join(root, 'expected.json'), 'utf8'))
const dataDir = join(root, expected.dataset)
const readJsonl = (p) =>
  existsSync(p)
    ? readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
    : []

// Phase normalization (INPUT_METADATA §Phase resolution)
const PHASES = {
  NC: ['NC', 'NONCONTRAST', 'NON-CONTRAST'],
  CMP: ['ART', 'ARTERIAL', 'CMP', 'CORTICOMEDULLARY'],
  NP: ['VEN', 'VENOUS', 'NP', 'NEPHROGRAPHIC', 'PORTAL'],
  EP: ['EP', 'DELAY', 'DELAYED', 'EXC', 'EXCRETORY'],
}
const canonical = (raw) => {
  const v = String(raw ?? '').toUpperCase()
  for (const [c, list] of Object.entries(PHASES)) if (list.includes(v)) return c
  return 'UNK'
}

const ERROR_CODES = new Set([
  'missing_path', 'unreadable_file', 'outside_root',
  'affine_mismatch', 'shape_mismatch', 'duplicate_row_identity',
])

// Minimal NIfTI-1 reader: the header fields we need + voxel data (int16 / uint8 / float32)
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
  const spacing = [1, 2, 3].map((i) => +dv.getFloat32(76 + i * 4, true).toFixed(3))
  const off = Math.round(dv.getFloat32(108, true))
  const n = dim[0] * dim[1] * dim[2]
  const data = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    if (datatype === 4) data[i] = dv.getInt16(off + i * 2, true)
    else if (datatype === 2) data[i] = dv.getUint8(off + i)
    else if (datatype === 16) data[i] = dv.getFloat32(off + i * 4, true)
  }
  const dtype = { 2: 'uint8', 4: 'int16', 16: 'float32' }[datatype] ?? `dt${datatype}`
  return { dim, spacing, dtype, data }
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

function labelStats(img, seg, label) {
  const [nx, ny] = img.dim
  const vals = []
  let faces = 0
  let neighbourSq = 0
  let neighbourN = 0
  const isL = (i) => seg.data[i] === label
  for (let i = 0; i < seg.data.length; i++) {
    if (!isL(i)) continue
    vals.push(img.data[i])
    for (const d of [1, nx, nx * ny]) {
      if (!isL(i + d)) faces++
      else {
        neighbourSq += (img.data[i] - img.data[i + d]) ** 2
        neighbourN++
      }
      if (!isL(i - d)) faces++
    }
  }
  if (vals.length === 0) return null
  vals.sort((a, b) => a - b)
  const n = vals.length
  const q = (p) => vals[Math.min(n - 1, Math.floor(p * n))]
  const mean = vals.reduce((s, v) => s + v, 0) / n
  const sd = Math.sqrt(vals.reduce((s, v) => s + (v - mean) ** 2, 0) / n)
  const m3 = vals.reduce((s, v) => s + (v - mean) ** 3, 0) / n
  const m4 = vals.reduce((s, v) => s + (v - mean) ** 4, 0) / n
  const bins = new Map()
  for (const v of vals) bins.set(Math.floor(v / 25), (bins.get(Math.floor(v / 25)) ?? 0) + 1)
  const entropy = -[...bins.values()].reduce((s, c) => s + (c / n) * Math.log2(c / n), 0)
  const [sx, sy, sz] = img.spacing
  const voxVol = sx * sy * sz
  const volume = n * voxVol
  const area = faces * ((sx * sy + sy * sz + sx * sz) / 3)
  const sphericity = (Math.cbrt(36 * Math.PI * volume * volume)) / area
  const contrast = neighbourN ? neighbourSq / neighbourN / 625 : 0
  return {
    firstorder: {
      Mean: mean, Median: q(0.5), Minimum: vals[0], Maximum: vals[n - 1],
      '10Percentile': q(0.1), '90Percentile': q(0.9), StandardDeviation: sd,
      Skewness: sd ? m3 / sd ** 3 : 0, Kurtosis: sd ? m4 / sd ** 4 : 0, Entropy: entropy,
      Range: vals[n - 1] - vals[0], InterquartileRange: q(0.75) - q(0.25),
    },
    shape: {
      VoxelVolume: volume, MeshVolume: volume * 0.97, SurfaceArea: area,
      Sphericity: sphericity, SurfaceVolumeRatio: area / volume,
      Maximum3DDiameter: 2 * Math.cbrt((3 * volume) / (4 * Math.PI)) * (1.1 - sphericity * 0.1),
    },
    glcm: {
      Contrast: contrast,
      Correlation: Math.max(0, 1 - contrast / (1 + sd / 25)),
      JointEntropy: entropy * 1.6,
      Idm: 1 / (1 + contrast),
    },
    glrlm: { RunLengthNonUniformity: n / (1 + contrast), ShortRunEmphasis: 0.9 - 0.4 / (1 + contrast) },
    glszm: { ZoneEntropy: entropy + 1.2, SmallAreaEmphasis: 0.4 + 0.3 * (1 - sphericity) },
  }
}

// ---- index -------------------------------------------------------------
const rows = readJsonl(join(dataDir, 'metadata.jsonl'))
const phaseJson = existsSync(join(dataDir, 'phase.json'))
  ? JSON.parse(readFileSync(join(dataDir, 'phase.json'), 'utf8'))
  : { phases: [] }
const override = new Map(phaseJson.phases.map((p) => [`${p.case_id}.${p.scan_idx}`, p.phase]))
const vois = readJsonl(join(dataDir, 'voi/voi_catalog.jsonl'))
const excluded = new Set(expected.excluded_upstream ?? [])

const items = []
const slices = {}
const volumes = new Map()
const warnings = []
const seen = new Set()
const warn = (code, rec, message, extra = {}) => {
  const key = `${code}|${rec.item_id ?? rec.case_id}`
  if (seen.has(key)) return
  seen.add(key)
  warnings.push({
    code, severity: ERROR_CODES.has(code) ? 'error' : 'warning',
    item_id: rec.item_id ?? null, case_id: rec.case_id, message,
    detected_at: '2026-09-23T09:00:00Z', ...extra,
  })
}

for (const row of rows) {
  const key = `${row.case_id}.${row.scan_idx}`
  const rawPhase = override.get(key) ?? row.curated_phase ?? row.canonical_phase ?? row.phase ?? row.phase_guess
  const phase = { canonical: canonical(rawPhase), raw: rawPhase ?? '', source: override.has(key) ? 'phase.json' : 'metadata.jsonl' }
  const rel = row.relative_path ?? row.filename ?? ''
  const segRel = row.seg_path ?? (row.filename ? `seg/${row.filename.replace(/_0000(\.nii(\.gz)?)$/, '$1')}` : '')
  const img = rel ? readNifti(join(dataDir, rel)) : null
  const seg = segRel ? readNifti(join(dataDir, segRel)) : null
  const item_id = `${row.case_id}.${row.scan_idx}.complete.-`
  // Duplicate identity: the first row wins; the defect is reported via expected.json (IMP-08)
  if (items.some((i) => i.item_id === item_id)) continue
  const status = excluded.has(row.case_id) ? 'excluded_upstream' : img ? 'active' : 'missing'
  const item = {
    item_id, case_id: row.case_id, scan_idx: row.scan_idx, scope: 'complete', side: '-',
    patient_id: row.patient_id ?? '', group: row.group ?? '', phase,
    image: rel ? { ref: `DATA:${rel}`, format: 'nifti' } : null,
    mask: seg ? { ref: `DATA:${segRel}`, format: 'nifti' } : null,
    geometry: img ? { shape: img.dim, spacing: img.spacing, dtype: img.dtype, orientation: 'RAS' } : null,
    labels_present: seg ? [1, 2, 3].filter((l) => seg.data.includes(l)) : [],
    status, warning_codes: [], extra: { series_uid: row.series_uid ?? null, upstream_status: row.status ?? null },
  }
  items.push(item)
  if (img) {
    volumes.set(item_id, { img, seg })
    const s = midSlices(img, Int16Array)
    const m = seg && seg.dim.join() === img.dim.join() ? midSlices(seg, Uint8Array) : null
    slices[item_id] = { image: s, mask: m }
    if (!seg && status === 'active') warn('missing_seg', item, 'Scan has no SEG')
  }
  if (phase.canonical === 'UNK' && status !== 'excluded_upstream') warn('ambiguous_phase', item, `Phase "${phase.raw}" resolved to UNK`)
}

for (const v of vois) {
  const item_id = `${v.case_id}.${v.scan_idx}.voi.${v.side}`
  const parent = items.find((i) => i.case_id === v.case_id && i.scan_idx === v.scan_idx)
  const img = v.image_path.endsWith('.nii.gz') ? readNifti(join(dataDir, v.image_path)) : null
  const imgExists = existsSync(join(dataDir, v.image_path))
  items.push({
    item_id, case_id: v.case_id, scan_idx: v.scan_idx, scope: 'voi', side: v.side,
    patient_id: parent?.patient_id ?? '', group: v.group ?? parent?.group ?? '',
    phase: parent?.phase ?? { canonical: canonical(v.phase), raw: v.phase ?? '', source: 'voi_catalog' },
    image: { ref: `DATA:${v.image_path}`, format: v.image_path.endsWith('.npy') ? 'npy' : 'nifti' },
    mask: v.mask_path && existsSync(join(dataDir, v.mask_path)) ? { ref: `DATA:${v.mask_path}`, format: 'nifti' } : null,
    geometry: img ? { shape: img.dim, spacing: img.spacing, dtype: img.dtype, orientation: 'RAS' } : null,
    labels_present: [], status: imgExists ? 'active' : 'missing', warning_codes: [], extra: {},
  })
}

for (const d of expected.defects) {
  const scope = d.side ? 'voi' : 'complete'
  const item_id = `${d.case_id}.${d.scan_idx}.${scope}.${d.side ?? '-'}`
  const rec = items.find((i) => i.item_id === item_id) ?? { case_id: d.case_id }
  warn(d.code, { case_id: d.case_id, item_id: rec.item_id ?? null }, d.note)
}
for (const w of warnings) {
  const it = items.find((i) => i.item_id === w.item_id)
  if (it && !it.warning_codes.includes(w.code)) it.warning_codes.push(w.code)
}

// ---- radiomics run (complete scope, labels kidney + tumor) --------------
const features = []
const errors = []
const runItems = items.filter((i) => i.scope === 'complete' && i.status === 'active')
for (const it of runItems) {
  const v = volumes.get(it.item_id)
  if (!v?.seg) continue
  if (v.seg.dim.join() !== v.img.dim.join()) {
    errors.push({ item_id: it.item_id, label: 2, error: 'Mask geometry does not match image (shape)' })
    continue
  }
  for (const label of [1, 2]) {
    const st = labelStats(v.img, v.seg, label)
    if (!st) continue
    for (const [cls, feats] of Object.entries(st))
      for (const [name, value] of Object.entries(feats))
        features.push({ item_id: it.item_id, label, feature_class: cls, feature: `${cls}_${name}`, value: +value.toFixed(4) })
  }
}

// ---- deterministic spread (mulberry32 seeded by the fixture seed) ------------
function rng(seed) {
  return () => {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const rand = rng(expected.seed)
const gauss = () => Math.sqrt(-2 * Math.log(rand() + 1e-12)) * Math.cos(2 * Math.PI * rand())
const LOCATION = new Set(['Mean', 'Median', 'Minimum', 'Maximum', '10Percentile', '90Percentile'])
const defectOf = new Map(expected.defects.map((d) => [`${d.case_id}.${d.scan_idx}.complete.-`, d.code]))
const factors = new Map()
for (const f of features) {
  if (!factors.has(f.item_id)) {
    const d = defectOf.get(f.item_id)
    const shift = d === 'affine_mismatch' ? 160 : d === 'ambiguous_phase' ? -70 : 0
    factors.set(f.item_id, { size: Math.exp(0.35 * gauss()), hu: 12 * gauss() + shift, tex: Math.exp(0.2 * gauss()) })
  }
  const k = factors.get(f.item_id)
  const name = f.feature.slice(f.feature_class.length + 1)
  if (f.feature_class === 'shape') {
    const p = /Volume$/.test(name) ? 1 : name === 'SurfaceArea' ? 2 / 3 : name === 'Maximum3DDiameter' ? 1 / 3 : name === 'SurfaceVolumeRatio' ? -1 / 3 : 0
    f.value = +(f.value * k.size ** p).toFixed(4)
  } else if (f.feature_class === 'firstorder' && LOCATION.has(name)) f.value = +(f.value + k.hu).toFixed(4)
  else if (f.feature_class !== 'firstorder') f.value = +(f.value * k.tex).toFixed(4)
  else f.value = +(f.value * (1 + 0.05 * gauss())).toFixed(4)
}

const run = {
  run_id: '01JRUN0NPTUMOR0BASELINE001', name: 'Kidney + tumor baseline', status: errors.length ? 'completed_with_errors' : 'completed',
  created_at: '2026-09-23T10:02:00Z', started_at: '2026-09-23T10:02:05Z', finished_at: '2026-09-23T10:06:41Z',
  reviewer: 'Dr. AP', engine: { name: 'pyradiomics', version: '3.x (mock)' },
  profile_hash: 'sha256:9f2c…e41a', selection: { scope: 'complete', labels: [1, 2], filter: 'status=active' },
  counts: { items: runItems.length, ok: runItems.length - errors.length, failed: errors.length, features: new Set(features.map((f) => f.feature)).size },
}

const seed = {
  generated_from: { dataset: expected.dataset, seed: expected.seed },
  items, warnings, runs: [run], features: { [run.run_id]: features }, errors: { [run.run_id]: errors },
}
writeFileSync(join(outDir, 'seed.json'), JSON.stringify(seed))
writeFileSync(join(outDir, 'slices.json'), JSON.stringify(slices))
console.log(`mock seed: ${items.length} items, ${warnings.length} warnings, ${features.length} feature values, ${Object.keys(slices).length} slice sets`)
