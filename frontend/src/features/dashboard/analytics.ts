// Client-side stand-ins for the API-38 dashboard views (DB-05 moves these server-side in P6).
// Pure functions over the long feature table; no inferential statistics (DASHBOARD §Purpose).
import type { FeatureRow } from '../../api'
import { robustZ } from '../../lib'

export interface WideRow {
  key: string
  item_id: string
  case_id: string
  phase: string
  group: string
  label: number
  values: Record<string, number>
}

export function toWide(rows: FeatureRow[]): { rows: WideRow[]; features: string[] } {
  const map = new Map<string, WideRow>()
  const feats = new Set<string>()
  for (const r of rows) {
    const key = `${r.item_id}|${r.label}`
    let w = map.get(key)
    if (!w) {
      w = { key, item_id: r.item_id, case_id: r.case_id, phase: r.phase, group: r.group, label: r.label, values: {} }
      map.set(key, w)
    }
    w.values[r.feature] = r.value
    feats.add(r.feature)
  }
  return { rows: [...map.values()], features: [...feats].sort() }
}

export interface Outlier {
  row: WideRow
  feature: string
  z: number
}

/** Top outliers by |robust z| per item (median/MAD); threshold default 3.5 */
export function outliers(rows: WideRow[], features: string[], threshold = 3.5): Outlier[] {
  const zf = new Map(features.map((f) => [f, robustZ(rows.map((r) => r.values[f] ?? NaN).filter(Number.isFinite))]))
  const out: Outlier[] = []
  for (const row of rows) {
    let best: Outlier | null = null
    for (const f of features) {
      const v = row.values[f]
      const z = v === undefined ? 0 : (zf.get(f)?.(v) ?? 0)
      if (!best || Math.abs(z) > Math.abs(best.z)) best = { row, feature: f, z }
    }
    if (best && Math.abs(best.z) >= threshold) out.push(best)
  }
  return out.sort((a, b) => Math.abs(b.z) - Math.abs(a.z))
}

export function zScores(rows: WideRow[], features: string[]): number[][] {
  const stats = features.map((f) => {
    const vs = rows.map((r) => r.values[f] ?? 0)
    const mean = vs.reduce((s, v) => s + v, 0) / (vs.length || 1)
    const sd = Math.sqrt(vs.reduce((s, v) => s + (v - mean) ** 2, 0) / (vs.length || 1)) || 1
    return [mean, sd] as const
  })
  return rows.map((r) => features.map((f, j) => ((r.values[f] ?? 0) - (stats[j]?.[0] ?? 0)) / (stats[j]?.[1] ?? 1)))
}

/** PCA to 2 components by power iteration with deflation (small p) */
export function pca2(X: number[][]): { points: [number, number][]; explained: [number, number] } {
  const n = X.length
  const p = X[0]?.length ?? 0
  if (n < 3 || p < 2) return { points: X.map(() => [0, 0]), explained: [0, 0] }
  const C = Array.from({ length: p }, (_, i) =>
    Array.from({ length: p }, (_, j) => X.reduce((s, row) => s + (row[i] ?? 0) * (row[j] ?? 0), 0) / (n - 1)),
  )
  const trace = C.reduce((s, row, i) => s + (row[i] ?? 0), 0) || 1
  const comps: number[][] = []
  const eig: number[] = []
  for (let k = 0; k < 2; k++) {
    let v = Array.from({ length: p }, (_, i) => Math.sin(i + 1 + k))
    let lambda = 0
    for (let it = 0; it < 200; it++) {
      const w = C.map((row) => row.reduce((s, c, j) => s + c * (v[j] ?? 0), 0))
      const norm = Math.hypot(...w) || 1
      lambda = norm
      v = w.map((x) => x / norm)
    }
    comps.push(v)
    eig.push(lambda)
    for (let i = 0; i < p; i++) for (let j = 0; j < p; j++) (C[i] as number[])[j] = (C[i]?.[j] ?? 0) - lambda * (v[i] ?? 0) * (v[j] ?? 0)
  }
  const proj = (row: number[], c: number[]) => row.reduce((s, x, j) => s + x * (c[j] ?? 0), 0)
  return {
    points: X.map((row) => [proj(row, comps[0] ?? []), proj(row, comps[1] ?? [])]),
    explained: [(eig[0] ?? 0) / trace, (eig[1] ?? 0) / trace],
  }
}

function ranks(v: number[]): number[] {
  const idx = v.map((x, i) => [x, i] as const).sort((a, b) => a[0] - b[0])
  const r = new Array<number>(v.length)
  idx.forEach(([, i], k) => (r[i] = k))
  return r
}

export function spearman(a: number[], b: number[]): number {
  const ra = ranks(a)
  const rb = ranks(b)
  const n = a.length
  const ma = (n - 1) / 2
  let num = 0
  let da = 0
  let db = 0
  for (let i = 0; i < n; i++) {
    const x = (ra[i] ?? 0) - ma
    const y = (rb[i] ?? 0) - ma
    num += x * y
    da += x * x
    db += y * y
  }
  return da && db ? num / Math.sqrt(da * db) : 0
}

export function histogram(values: number[], bins = 12): { edges: number[]; counts: number[] } {
  if (!values.length) return { edges: [], counts: [] }
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const w = (hi - lo) / bins || 1
  const counts = new Array<number>(bins).fill(0)
  for (const v of values) counts[Math.min(bins - 1, Math.floor((v - lo) / w))]! += 1
  return { edges: Array.from({ length: bins + 1 }, (_, i) => lo + i * w), counts }
}
