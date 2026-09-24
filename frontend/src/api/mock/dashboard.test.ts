import type { FeatureRow } from '../types'
import { histogram, mockDashboardView, pca2, spearman, toWide, zScores } from './dashboard'

const row = (item: string, feature: string, value: number | null): FeatureRow => ({
  item_id: item, case_id: item.split('.')[0] ?? '', scan_idx: '01', scope: 'complete', side: '-', phase: 'NP', label: 2,
  image_type: 'original', feature_class: 'firstorder', feature, value, ibsi_code: null, ibsi_status: null,
})

describe('mock dashboard views', () => {
  const long = Array.from({ length: 12 }, (_, i) => [
    row(`c${i}.01.complete.-`, 'original_firstorder_a', i === 11 ? 500 : 10 + (i % 3)),
    row(`c${i}.01.complete.-`, 'original_shape_MeshVolume', i * 2),
  ]).flat()
  const data = { rows: long, errors: [], run: undefined, statusOf: new Map() }

  test('long → wide skips null values', () => {
    const w = toWide([...long, row('c0.01.complete.-', 'original_firstorder_b', null)])
    expect(w.features).toEqual(['original_firstorder_a', 'original_firstorder_b', 'original_shape_MeshVolume'])
    expect(w.rows).toHaveLength(12)
    expect(w.rows[3]?.values).toEqual({ original_firstorder_a: 10, original_shape_MeshVolume: 6 })
  })
  test('outliers view flags the injected outlier first', () => {
    const out = mockDashboardView('outliers', {}, data)
    expect(out.items[0]?.item_id).toBe('c11.01.complete.-')
    expect(out.items[0]?.top_features[0]?.feature).toBe('original_firstorder_a')
  })
  test('feature vs volume ranks by |rho|', () => {
    const v = mockDashboardView('feature-vs-volume', { feature: 'original_firstorder_a' }, data)
    expect(v.points).toHaveLength(12)
    expect(v.ranked[0]?.feature).toBe('original_firstorder_a')
  })
  test('filters apply', () => {
    const v = mockDashboardView('feature-distribution', { feature: 'original_firstorder_a', filters: { item_ids: ['c1.01.complete.-'] } }, data)
    expect(v.points).toHaveLength(1)
  })
  test('statistics views need the backend', () => {
    expect(() => mockDashboardView('group-comparison', { variable: 'x' }, data)).toThrow()
  })
  test('spearman is rank-based', () => {
    expect(spearman([1, 2, 3, 4], [10, 20, 30, 1000])).toBeCloseTo(1)
    expect(spearman([1, 2, 3, 4], [4, 3, 2, 1])).toBeCloseTo(-1)
  })
  test('pca explains variance in order', () => {
    const w = toWide(long)
    const { points, explained } = pca2(zScores(w.rows, w.features))
    expect(points).toHaveLength(12)
    expect(explained[0]).toBeGreaterThanOrEqual(explained[1])
    expect(explained[0] + explained[1]).toBeLessThanOrEqual(1.0001)
  })
  test('histogram counts every value', () => {
    const h = histogram([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5)
    expect(h.counts.reduce((a, b) => a + b, 0)).toBe(10)
    expect(h.edges).toHaveLength(6)
  })
})
