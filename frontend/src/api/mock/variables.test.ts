// VARIABLES.md §Type inference rules, as implemented by the mock (the backend owns the real rules)
import { candidateFields, deriveValue, inferLevel, inferType, parseTable, profileField, validateDerived, type Row } from './variables'

const range = (n: number, f: (i: number) => unknown) => Array.from({ length: n }, (_, i) => f(i))

describe('type inference (VAR-03)', () => {
  test('continuous: ≥95 % numeric and ≥10 distinct', () => {
    expect(inferType(range(40, (i) => i * 2.5)).type).toBe('continuous')
    expect(inferType([...range(39, (i) => String(i)), 'n/a']).type).toBe('continuous')
  })
  test('numeric with <10 distinct needs review', () => {
    const r = inferType(range(40, (i) => [0, 5, 7, 8, 10, 30][i % 6]))
    expect(r.type).toBe('numeric-discrete')
    expect(r.confidence).toBeLessThan(0.8)
  })
  test('categorical, date, identifier, text, constant; empty string is missing', () => {
    expect(inferType(range(40, (i) => ['SIEMENS', 'Philips', 'GE'][i % 3])).type).toBe('categorical')
    expect(inferType(range(40, (i) => `2019-01-${String((i % 28) + 1).padStart(2, '0')}`)).type).toBe('date')
    expect(inferType(range(40, (i) => `2019${String((i % 12) + 1).padStart(2, '0')}15`)).type).toBe('date')
    expect(inferType(range(40, (i) => `uid-${i}-x`)).type).toBe('identifier')
    expect(inferType([...range(30, (i) => `note ${i % 25}`), ...range(10, () => 'same')]).type).toBe('text')
    expect(inferType(['converted', 'converted', '']).type).toBe('constant')
  })
})

describe('level, groups, tags, exclusions (VAR-02/04/05/09)', () => {
  const rows: Row[] = [
    { case_id: 'c1', patient_id: 'p1', values: { score: 10, kvp: 100, series_uid: '1.2.3', manufacturer: 'A' } },
    { case_id: 'c1', patient_id: 'p1', values: { score: 10, kvp: 120, series_uid: '1.2.4', manufacturer: 'A' } },
    { case_id: 'c2', patient_id: 'p2', values: { score: '', kvp: 100, series_uid: '1.2.5', manufacturer: 'B' } },
    { case_id: 'c3', patient_id: 'p3', values: { score: 20, kvp: 140, series_uid: '1.2.6', manufacturer: 'B' } },
  ]
  test('case-level when constant within every case', () => {
    expect(inferLevel(rows, 'score')).toBe('case')
    expect(inferLevel(rows, 'kvp')).toBe('scan')
  })
  test('unknown fields are Study and visible; known schema fields are Acquisition, hidden, and confounders', () => {
    const score = profileField(rows, 'score', 'metadata')
    expect(score).toMatchObject({ group: 'study', visible: true, level: 'case' })
    expect(score.profile.missing_pct).toBeCloseTo(33.3)
    const vendor = profileField(rows, 'manufacturer', 'metadata')
    expect(vendor).toMatchObject({ group: 'acquisition', visible: false, tags: ['confounder'] })
  })
  test('UIDs are never variables', () => {
    expect(candidateFields(rows)).toEqual(['kvp', 'manufacturer', 'score'])
  })
  test('overrides win and clear Review', () => {
    const v = profileField(rows, 'score', 'metadata', { type: 'categorical', visible: false })
    expect(v).toMatchObject({ type: 'categorical', visible: false, overridden: true, review: false })
  })
})

describe('derived variables and external tables (VAR-06/07)', () => {
  const all: Row[] = [10, 40, 60, 90].map((x, i) => ({ case_id: `c${i}`, patient_id: null, values: { a: x, b: 100 - x, v: ['SIEMENS', 'Siemens'][i % 2] } }))
  test('bin, recode, dominant', () => {
    expect(all.map((r) => deriveValue({ name: 'g', op: 'bin', source: 'a', thresholds: [50], labels: ['low', 'high'] }, r.values, all))).toEqual(['low', 'low', 'high', 'high'])
    expect(all.map((r) => deriveValue({ name: 'q', op: 'bin', source: 'a', quantiles: 2, labels: ['Q1', 'Q2'] }, r.values, all))).toEqual(['Q1', 'Q1', 'Q2', 'Q2'])
    expect(deriveValue({ name: 'r', op: 'recode', source: 'v', map: { SIEMENS: 'Siemens' } }, all[0]?.values ?? {}, all)).toBe('Siemens')
    expect(all.map((r) => deriveValue({ name: 'd', op: 'dominant', sources: ['a', 'b'] }, r.values, all))).toEqual(['b', 'b', 'a', 'a'])
  })
  test('validation', () => {
    const known = new Set(['a', 'b'])
    expect(validateDerived({ name: 'a', op: 'dominant', sources: ['a', 'b'] }, known)).toMatch(/already exists/)
    expect(validateDerived({ name: 'x', op: 'bin', source: 'a', thresholds: [1], labels: ['one'] }, known)).toMatch(/2 labels/)
    expect(validateDerived({ name: 'x', op: 'bin', source: 'a', thresholds: [1], labels: ['lo', 'hi'] }, known)).toBeNull()
  })
  test('CSV and TSV parse', () => {
    expect(parseTable('case_id,score\n"c1",3\n\nc2,4\n')).toEqual({ header: ['case_id', 'score'], rows: [['c1', '3'], ['c2', '4']] })
    expect(parseTable('case_id\tscore\nc1\t3').rows).toEqual([['c1', '3']])
  })
})
