// Contract adapter for API-16..18: backend Catalog → UI Variable[] (integration of lane/2-shell and lane/2-backend).
import { afterEach, expect, test, vi } from 'vitest'

import { httpApi } from './http'

const catalog = {
  schema_version: 1,
  profiled_at: '2026-09-24T00:00:00Z',
  import_id: 'imp',
  n_items: 10,
  n_cases: 5,
  variables: [
    {
      name: 'score', source: 'metadata', type: 'continuous', inferred_type: 'continuous', level: 'case',
      group: 'study', tags: ['outcome'], visible: true, confidence: 0.9, review: false, overridden: false,
      profile: { n_units: 5, n_missing: 1, missing_pct: 20, distinct: 4, top: [], examples: ['1', '2'], numeric_pct: 100, min: 0, max: 90, median: 40 },
    },
    {
      name: 'score_tertile', source: 'derived', type: 'categorical', inferred_type: 'categorical', level: 'case',
      group: 'study', visible: true, confidence: 1, review: false, overridden: false,
      profile: { n_units: 5, n_missing: 0, missing_pct: 0, distinct: 3, top: [{ value: 'low', n: 2 }, { value: 'mid', n: 2 }], examples: [], numeric_pct: 0 },
    },
  ],
  excluded: [],
  derived: [{ op: 'bin', name: 'score_tertile', source: 'score', quantiles: [1 / 3, 2 / 3], labels: ['low', 'mid', 'high'] }],
  external: [],
  overrides: {},
}

function mockFetch(body: unknown) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

test('listVariables maps Catalog profile names and derived definitions', async () => {
  mockFetch(catalog)
  const vars = await httpApi.listVariables('p1')
  expect(vars).toHaveLength(2)
  expect(vars[0]?.profile.n_distinct).toBe(4)
  expect(vars[1]?.tags).toEqual([])
  expect(vars[1]?.profile.levels).toEqual([{ value: 'low', count: 2 }, { value: 'mid', count: 2 }])
  expect(vars[1]?.definition).toMatchObject({ op: 'bin', quantiles: 3, labels: ['low', 'mid', 'high'] })
})

test('createDerived sends quantile cut probabilities and returns the created variable', async () => {
  const fn = mockFetch(catalog)
  const v = await httpApi.createDerived('p1', { name: 'score_tertile', op: 'bin', source: 'score', quantiles: 3, labels: ['low', 'mid', 'high'] })
  const init = (fn.mock.calls[0] as unknown as [string, RequestInit])[1]
  expect(JSON.parse(String(init.body)).quantiles).toEqual([1 / 3, 2 / 3])
  expect(v.name).toBe('score_tertile')
})
