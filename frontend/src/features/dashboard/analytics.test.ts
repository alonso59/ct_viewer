import type { FeatureRow } from '../../api'
import { histogram, outliers, pca2, spearman, toWide, zScores } from './analytics'

const row = (item: string, feature: string, value: number): FeatureRow => ({
  item_id: item, label: 2, feature_class: 'firstorder', feature, value,
  case_id: item.split('.')[0] ?? '', scan_idx: '01', scope: 'complete', side: '-', phase: 'NP', group: 'A',
})

describe('dashboard analytics', () => {
  const long = Array.from({ length: 12 }, (_, i) => [row(`c${i}.01.complete.-`, 'a', i === 11 ? 500 : 10 + (i % 3)), row(`c${i}.01.complete.-`, 'b', i * 2)]).flat()

  test('long → wide', () => {
    const w = toWide(long)
    expect(w.features).toEqual(['a', 'b'])
    expect(w.rows).toHaveLength(12)
    expect(w.rows[3]?.values).toEqual({ a: 10, b: 6 })
  })
  test('robust z flags the injected outlier', () => {
    const w = toWide(long)
    const out = outliers(w.rows, ['a'], 3.5)
    expect(out.map((o) => o.row.item_id)).toEqual(['c11.01.complete.-'])
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
