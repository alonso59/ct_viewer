import type { Variable } from '../../api'
import { activeFilterCount } from './store'
import { colorable, filterable, formatValue, levelColor, parseRange, rangeValue } from './vars'

const v = (p: Partial<Variable>): Variable => ({
  name: 'x', source: 'metadata', type: 'categorical', inferred_type: 'categorical', level: 'case', group: 'study',
  tags: [], visible: true, confidence: 1, review: false, overridden: false,
  profile: { missing_pct: 0, n_distinct: 2, examples: [], levels: [{ value: 'B', count: 5 }, { value: 'A', count: 3 }] },
  ...p,
})

describe('explorer variables (VAR-10)', () => {
  test('level colours are stable by value, not by count', () => {
    expect(levelColor(v({}), 'A')).toBe('var(--cat-1)')
    expect(levelColor(v({}), 'B')).toBe('var(--cat-2)')
    expect(levelColor(v({}), null)).toBeNull()
    expect(levelColor(v({}), 'Z')).toBeNull()
  })
  test('filters: visible categorical or continuous only; colour: case-level categorical', () => {
    const vars = [v({ name: 'a' }), v({ name: 'b', type: 'continuous' }), v({ name: 'c', type: 'text' }), v({ name: 'd', visible: false }), v({ name: 'e', level: 'scan' })]
    expect(filterable(vars).map((x) => x.name)).toEqual(['a', 'b', 'e'])
    expect(colorable(vars).map((x) => x.name)).toEqual(['a'])
  })
  test('range filter round-trip', () => {
    expect(rangeValue('', '')).toBe('')
    expect(rangeValue('10', '')).toBe('10..')
    expect(parseRange('10..50')).toEqual(['10', '50'])
    expect(parseRange(undefined)).toEqual(['', ''])
  })
  test('values format with Intl and show a dash when missing', () => {
    expect(formatValue(v({ type: 'continuous' }), 1234.567)).toBe('1,235')
    expect(formatValue(undefined, null)).toBe('—')
  })
  test('variable filters count as active filters', () => {
    expect(activeFilterCount({ q: 'x', vars: { a: 'A', b: '' } })).toBe(1)
  })
})
