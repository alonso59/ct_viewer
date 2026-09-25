import type { ResultRow, Variable } from '../../../api'
import { analysisVariables, confounderVariables, fmtP, fmtStat, needsConfirmation, questionsFor, sortResults, suggestedConfounder, viewForResult } from './model'

const v = (name: string, type: Variable['type'], extra: Partial<Variable> = {}): Variable => ({
  name, source: 'metadata', type, inferred_type: type, level: 'case', group: 'study', tags: [], visible: true,
  confidence: 1, review: false, overridden: false, comparable: false, profile: { missing_pct: 0, n_distinct: 3, examples: [] }, ...extra,
})

const row = (feature: string, q: number | null, effect: number | null): ResultRow => ({ feature, test: 'welch_t', reason: '', q, effect, n: 10 })

describe('analysis panel model', () => {
  test('ANA-02: questions per variable type', () => {
    expect(questionsFor(null)).toEqual(['explore'])
    expect(questionsFor(v('a', 'categorical'))).toEqual(['compare', 'balance'])
    expect(questionsFor(v('a', 'continuous'))).toEqual(['association'])
    expect(questionsFor(v('a', 'numeric-discrete'))).toEqual([])
    expect(needsConfirmation(v('a', 'numeric-discrete'))).toBe(true)
    expect(questionsFor(v('a', 'date'))).toEqual([])
  })

  test('variable lists', () => {
    const vars = [
      v('z_scan', 'categorical', { level: 'scan' }), v('age', 'continuous'), v('when', 'date'), v('hidden', 'continuous', { visible: false }),
      v('grade', 'numeric-discrete'), v('vendor', 'categorical', { visible: false, group: 'acquisition', tags: ['confounder'] }), v('sex', 'categorical'),
    ]
    expect(analysisVariables(vars).map((x) => x.name)).toEqual(['age', 'grade', 'sex', 'z_scan'])
    expect(confounderVariables(vars, 'sex').map((x) => x.name)).toEqual(['vendor', 'z_scan'])
    expect(suggestedConfounder(vars, null)).toBe('vendor')
    expect(suggestedConfounder(vars, 'vendor')).toBeNull()
  })

  test('ANA-05: sort by q, then |effect|; untested last', () => {
    const out = sortResults([row('a', 0.2, 0.1), row('b', null, 5), row('c', 0.01, -0.3), row('d', 0.01, 0.9), row('e', NaN, 1)])
    expect(out.map((r) => r.feature)).toEqual(['d', 'c', 'a', 'b', 'e'])
  })

  test('number formatting', () => {
    expect(fmtP(0.04213)).toBe('0.042')
    expect(fmtP(1.47e-6)).toBe('1.47E-6')
    expect(fmtP(null)).toBe('—')
    expect(fmtP(0)).toBe('0')
    expect(fmtStat(0.83939)).toBe('0.839')
    expect(fmtStat(26.8604)).toBe('26.9')
    expect(fmtStat(Infinity)).toBe('—')
  })

  test('DB-09: result row → view', () => {
    expect(viewForResult('compare')).toBe('group-comparison')
    expect(viewForResult('association')).toBe('association')
    expect(viewForResult('explore')).toBeNull()
  })
})
