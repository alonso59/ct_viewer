import { defaultLabels, parseNumbers, toDefinition, type DerivedDraft } from './derived'

const draft = (p: Partial<DerivedDraft>): DerivedDraft => ({
  name: 'score_bin', op: 'bin', source: 'score', mode: 'thresholds', thresholds: '50', quantiles: '4', labels: '', map: {}, sources: [], ...p,
})

describe('derived variable form (VAR-06)', () => {
  test('bin by thresholds gets default labels', () => {
    expect(toDefinition(draft({}))).toEqual({ def: { name: 'score_bin', op: 'bin', source: 'score', thresholds: [50], labels: ['<50', '≥50'] } })
    expect(defaultLabels([10, 50], null)).toEqual(['<10', '10–50', '≥50'])
  })
  test('bin by quantiles and label count check', () => {
    expect(toDefinition(draft({ mode: 'quantiles', quantiles: '3' }))).toMatchObject({ def: { quantiles: 3, labels: ['Q1', 'Q2', 'Q3'] } })
    expect(toDefinition(draft({ thresholds: '10, 50', labels: 'low, high' }))).toEqual({ error: 'variables.err.labels' })
  })
  test('recode keeps only changed levels; dominant needs two sources', () => {
    expect(toDefinition(draft({ op: 'recode', source: 'vendor', map: { SIEMENS: 'Siemens', Philips: 'Philips', GE: ' ' } }))).toEqual({
      def: { name: 'score_bin', op: 'recode', source: 'vendor', map: { SIEMENS: 'Siemens' } },
    })
    expect(toDefinition(draft({ op: 'dominant', sources: ['a'] }))).toEqual({ error: 'variables.err.sources' })
    expect(toDefinition(draft({ op: 'dominant', sources: ['a', 'b'] }))).toEqual({ def: { name: 'score_bin', op: 'dominant', sources: ['a', 'b'] } })
  })
  test('names and numbers are validated', () => {
    expect(toDefinition(draft({ name: 'Bad Name' }))).toEqual({ error: 'variables.err.name' })
    expect(parseNumbers('1, x')).toBeNull()
    expect(parseNumbers('1 2;3')).toEqual([1, 2, 3])
  })
})
