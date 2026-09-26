// Mock API-38 views (VITE_API_MODE=mock): client-side stand-ins over the seeded long feature table,
// shaped like the real responses. `var` filters and variable colouring are not modelled; the guided
// statistics (group comparison, association, balance, phase/side consistency) need the backend (SciPy).
import { robustZ } from '../../lib/format'
import { ProblemError } from '../problem'
import type { ColorBy, CurationStatus, DashboardView, FeatureRow, GlobalFilters, RunError, RunSummary, ViewRequest, ViewResponse } from '../types'

export interface MockRunData {
  rows: FeatureRow[]
  errors: RunError[]
  run: RunSummary | undefined
  /** CUR-08 case rollup */
  statusOf: Map<string, CurationStatus>
}

// ---- pure helpers (tested in dashboard.test.ts) -------------------------------------------------
export interface WideRow {
  key: string
  item_id: string
  case_id: string
  phase: string
  scope: string
  side: string
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
      w = { key, item_id: r.item_id, case_id: r.case_id, phase: r.phase, scope: r.scope, side: r.side, label: r.label, values: {} }
      map.set(key, w)
    }
    if (r.value !== null) w.values[r.feature] = r.value
    feats.add(r.feature)
  }
  return { rows: [...map.values()], features: [...feats].sort() }
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
export function pca2(X: number[][]): { points: [number, number][]; explained: [number, number]; components: number[][] } {
  const n = X.length
  const p = X[0]?.length ?? 0
  if (n < 3 || p < 2) return { points: X.map(() => [0, 0]), explained: [0, 0], components: [] }
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
    components: comps,
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

function quantile(sorted: number[], q: number): number | null {
  if (!sorted.length) return null
  const pos = (sorted.length - 1) * q
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  return (sorted[lo] ?? 0) + ((sorted[hi] ?? 0) - (sorted[lo] ?? 0)) * (pos - lo)
}

function box(values: number[]) {
  const s = [...values].sort((a, b) => a - b)
  const n = s.length
  const mean = n ? s.reduce((a, b) => a + b, 0) / n : null
  const sd = n > 1 && mean !== null ? Math.sqrt(s.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : null
  const q1 = quantile(s, 0.25)
  const q3 = quantile(s, 0.75)
  const iqr = q1 !== null && q3 !== null ? q3 - q1 : 0
  const inside = s.filter((v) => q1 !== null && q3 !== null && v >= q1 - 1.5 * iqr && v <= q3 + 1.5 * iqr)
  return {
    n, min: s[0] ?? null, q1, median: quantile(s, 0.5), q3, max: s[n - 1] ?? null,
    whisker_low: inside[0] ?? null, whisker_high: inside[inside.length - 1] ?? null, mean, sd,
  }
}

// ---- views ---------------------------------------------------------------------------------------
function applyFilters(rows: WideRow[], f: GlobalFilters | undefined, statusOf: Map<string, CurationStatus>): WideRow[] {
  if (!f) return rows
  return rows.filter(
    (r) =>
      (!f.phase?.length || f.phase.includes(r.phase)) &&
      (!f.scope?.length || f.scope.includes(r.scope as 'complete' | 'voi')) &&
      (!f.side?.length || f.side.includes(r.side as 'L' | 'R' | '-')) &&
      (!f.label?.length || f.label.includes(r.label)) &&
      (!f.status?.length || f.status.includes(statusOf.get(r.case_id) ?? 'not_reviewed')) &&
      (!f.item_ids?.length || f.item_ids.includes(r.item_id)),
  )
}

function colorOf(c: ColorBy | null | undefined, r: WideRow, statusOf: Map<string, CurationStatus>): string | null {
  if (!c) return null
  if (c.kind === 'phase') return r.phase
  if (c.kind === 'scope') return r.scope
  if (c.kind === 'side') return r.side
  if (c.kind === 'label') return String(r.label)
  if (c.kind === 'curation_status') return statusOf.get(r.case_id) ?? 'not_reviewed'
  return null
}

const VOLUME = 'original_shape_MeshVolume'

type Handler = (body: never, d: MockRunData & { wide: WideRow[]; features: string[] }) => unknown

const handlers: Partial<Record<DashboardView, Handler>> = {
  'run-overview': (body: ViewRequest<'run-overview'>, d): ViewResponse<'run-overview'> => {
    const rows = applyFilters(d.wide, body?.filters, d.statusOf)
    const items = new Set(rows.map((r) => r.item_id))
    const count = (vals: string[]) => [...vals.reduce((m, v) => m.set(v, (m.get(v) ?? 0) + 1), new Map<string, number>())].map(([level, n]) => ({ level, n }))
    const byItem = [...new Map(rows.map((r) => [r.item_id, r])).values()]
    const run = d.run
    return {
      run_id: run?.run_id ?? '', name: run?.name ?? '', status: run?.status ?? 'completed', created_at: run?.created_at ?? null,
      runtime_s: run?.started_at && run.finished_at ? (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000 : null,
      n_items_selected: items.size + new Set(d.errors.map((e) => e.item_id)).size,
      n_items_ok: items.size, n_features: d.features.length,
      n_items_failed: new Set(d.errors.filter((e) => e.kind !== 'skipped').map((e) => e.item_id)).size,
      n_items_skipped: new Set(d.errors.filter((e) => e.kind === 'skipped').map((e) => e.item_id)).size,
      per_label: [...new Set(rows.map((r) => r.label))].sort().map((label) => {
        const rs = rows.filter((r) => r.label === label)
        return { label, n_items: rs.length, n_values: rs.reduce((s, r) => s + Object.keys(r.values).length, 0) }
      }),
      per_phase: count(byItem.map((r) => r.phase)),
      curation: count(byItem.map((r) => d.statusOf.get(r.case_id) ?? 'not_reviewed')),
      n_errors: d.errors.length,
      errors: d.errors.map((e) => ({ item_id: e.item_id, case_id: e.item_id.split('.')[0] ?? null, label: e.label, message: e.error, kind: e.kind, code: e.code ?? null, detail: e.detail ?? null })),
      phase_changed: [],
    }
  },
  'feature-distribution': (body: ViewRequest<'feature-distribution'>, d): ViewResponse<'feature-distribution'> => {
    const rows = applyFilters(d.wide, body.filters, d.statusOf).filter((r) => r.values[body.feature] !== undefined)
    const tx = (v: number) => (body.log_scale ? Math.log10(Math.max(v, 1e-12)) : v)
    const { edges } = histogram(rows.map((r) => tx(r.values[body.feature] ?? 0)), body.bins ?? 30)
    const bins = edges.length - 1
    const binOf = (v: number) => Math.max(0, Math.min(bins - 1, Math.floor(((v - (edges[0] ?? 0)) / (((edges[bins] ?? 1) - (edges[0] ?? 0)) || 1)) * bins)))
    const levels = [...new Set(rows.map((r) => colorOf(body.split, r, d.statusOf)))]
    return {
      feature: body.feature, split: body.split ?? null, log_scale: body.log_scale ?? false, edges,
      groups: levels.map((level) => {
        const vs = rows.filter((r) => colorOf(body.split, r, d.statusOf) === level).map((r) => tx(r.values[body.feature] ?? 0))
        const counts = new Array<number>(Math.max(bins, 0)).fill(0)
        for (const v of vs) counts[binOf(v)]! += 1
        return { level, n: vs.length, n_missing: 0, counts, box: box(vs) }
      }),
      points: rows.map((r) => ({
        item_id: r.item_id, case_id: r.case_id, label: r.label, status: d.statusOf.get(r.case_id) ?? 'not_reviewed',
        color: colorOf(body.split, r, d.statusOf), value: r.values[body.feature] ?? 0, bin: binOf(tx(r.values[body.feature] ?? 0)),
      })),
      truncated: false,
    }
  },
  outliers: (body: ViewRequest<'outliers'>, d): ViewResponse<'outliers'> => {
    const rows = applyFilters(d.wide, body?.filters, d.statusOf)
    const threshold = body?.threshold ?? 3.5
    const zf = new Map(d.features.map((f) => [f, robustZ(rows.map((r) => r.values[f]).filter((v): v is number => v !== undefined))]))
    const counts = new Map<string, number>()
    const items = rows.map((r) => {
      const zs = d.features
        .filter((f) => r.values[f] !== undefined)
        .map((f) => ({ feature: f, value: r.values[f] ?? null, z: zf.get(f)?.(r.values[f] ?? 0) ?? 0 }))
        .sort((a, b) => Math.abs(b.z) - Math.abs(a.z))
      const out = zs.filter((z) => Math.abs(z.z) >= threshold)
      for (const o of out) counts.set(o.feature, (counts.get(o.feature) ?? 0) + 1)
      return {
        item_id: r.item_id, case_id: r.case_id, label: r.label, status: d.statusOf.get(r.case_id) ?? 'not_reviewed', color: null,
        max_abs_z: Math.abs(zs[0]?.z ?? 0), n_outlier_features: out.length, top_features: zs.slice(0, body?.top_features ?? 5),
      }
    })
    // as the backend: features over the threshold first, then max |z| (AUD-A2-06)
    const flagged = items.filter((i) => i.n_outlier_features > 0).sort((a, b) => b.n_outlier_features - a.n_outlier_features || b.max_abs_z - a.max_abs_z)
    return {
      threshold, n_items: rows.length, n_flagged: flagged.length, items: flagged.slice(0, body?.top_n ?? 10),
      features: [...counts].map(([feature, n]) => ({ feature, n_outlier_items: n })).sort((a, b) => b.n_outlier_items - a.n_outlier_items),
    }
  },
  embedding: (body: ViewRequest<'embedding'>, d): ViewResponse<'embedding'> => {
    const rows = applyFilters(d.wide, body?.filters, d.statusOf)
    const feats = body?.features?.length ? body.features : d.features
    const { points, explained, components } = pca2(zScores(rows, feats))
    const colors = rows.map((r) => colorOf(body?.color_by, r, d.statusOf))
    return {
      method: 'pca', n_components: 2, explained_variance_ratio: explained, features_used: feats,
      top_loadings: components.map((c) => feats.map((f, j) => ({ feature: f, weight: c[j] ?? 0 })).sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight)).slice(0, 5)),
      color_levels: [...new Set(colors.filter((c): c is string => c !== null))].sort(),
      points: rows.map((r, i) => ({
        item_id: r.item_id, case_id: r.case_id, label: r.label, status: d.statusOf.get(r.case_id) ?? 'not_reviewed',
        color: colors[i] ?? null, coords: points[i] ?? [0, 0],
      })),
    }
  },
  'feature-vs-volume': (body: ViewRequest<'feature-vs-volume'>, d): ViewResponse<'feature-vs-volume'> => {
    const rows = applyFilters(d.wide, body.filters, d.statusOf).filter((r) => r.values[VOLUME] !== undefined)
    const rho = (f: string) => {
      const rs = rows.filter((r) => r.values[f] !== undefined)
      return { rho: rs.length > 2 ? spearman(rs.map((r) => r.values[VOLUME] ?? 0), rs.map((r) => r.values[f] ?? 0)) : null, n: rs.length }
    }
    const sel = rho(body.feature)
    const colors = rows.map((r) => colorOf(body.color_by, r, d.statusOf))
    return {
      feature: body.feature, volume_feature: VOLUME, rho: sel.rho, p: null, n: sel.n, size_driven: Math.abs(sel.rho ?? 0) > 0.8,
      color_levels: [...new Set(colors.filter((c): c is string => c !== null))].sort(),
      points: rows
        .filter((r) => r.values[body.feature] !== undefined)
        .map((r) => ({
          item_id: r.item_id, case_id: r.case_id, label: r.label, status: d.statusOf.get(r.case_id) ?? 'not_reviewed',
          color: colorOf(body.color_by, r, d.statusOf), x: r.values[VOLUME] ?? 0, y: r.values[body.feature] ?? 0,
        })),
      ranked: d.features
        .filter((f) => f !== VOLUME)
        .map((f) => ({ feature: f, ...rho(f) }))
        .sort((a, b) => Math.abs(b.rho ?? 0) - Math.abs(a.rho ?? 0))
        .slice(0, body.top_n ?? 50),
    }
  },
  correlation: (body: ViewRequest<'correlation'>, d): ViewResponse<'correlation'> => {
    const rows = applyFilters(d.wide, body?.filters, d.statusOf)
    const threshold = body?.threshold ?? 0.9
    const feats = d.features.slice(0, body?.max_features ?? 200)
    const col = (f: string) => rows.map((r) => r.values[f] ?? 0)
    const matrix = feats.map((a) => feats.map((b) => (a === b ? 1 : spearman(col(a), col(b)))))
    // Greedy clusters of |rho| > threshold
    const seen = new Set<number>()
    const clusters: { features: string[] }[] = []
    feats.forEach((_, i) => {
      if (seen.has(i)) return
      const members = feats.map((_, j) => j).filter((j) => !seen.has(j) && Math.abs(matrix[i]?.[j] ?? 0) > threshold)
      members.forEach((j) => seen.add(j))
      if (members.length > 1) clusters.push({ features: members.map((j) => feats[j] ?? '') })
    })
    return { method: 'spearman', features: feats, matrix, threshold, clusters, n_rows: rows.length, truncated: d.features.length > feats.length }
  },
  'missing-matrix': (body: ViewRequest<'missing-matrix'>, d): ViewResponse<'missing-matrix'> => {
    const rows = applyFilters(d.wide, body?.filters, d.statusOf)
    const classOf = new Map(d.rows.map((r) => [r.feature, r.feature_class]))
    const cells: { item: number; feature: number; kind: 'nan' | 'inf' | 'absent' }[] = []
    rows.forEach((r, i) => d.features.forEach((f, j) => r.values[f] === undefined && cells.push({ item: i, feature: j, kind: 'nan' })))
    return {
      features: d.features.map((f, j) => ({ feature: f, feature_class: classOf.get(f) ?? '', n_nan: cells.filter((c) => c.feature === j).length, n_inf: 0, n_absent: 0 })),
      items: rows.map((r, i) => ({
        item_id: r.item_id, case_id: r.case_id, label: r.label, status: d.statusOf.get(r.case_id) ?? 'not_reviewed', color: null,
        n_invalid: cells.filter((c) => c.item === i).length,
      })),
      cells, n_items_total: rows.length, truncated: false,
    }
  },
}

export function mockDashboardView<V extends DashboardView>(view: V, body: ViewRequest<V>, data: MockRunData): ViewResponse<V> {
  const h = handlers[view]
  if (!h) throw new ProblemError(503, 'server-busy', 'Not available in the mock', `The ${view} view needs the backend (API-38)`)
  const { rows, features } = toWide(data.rows)
  return h(body as never, { ...data, wide: rows, features }) as ViewResponse<V>
}
