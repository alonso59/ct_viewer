import { caseOfItem, type Variable } from '../../api'
import { filterByItems } from '../../api/surface'
import { explorerSelection } from './selection'
import { activeFilterCount, useExplorer } from './store'

const v = (name: string, type: Variable['type']): Variable => ({
  name, source: 'metadata', type, inferred_type: type, level: 'case', group: 'study',
  tags: [], visible: true, confidence: 1, review: false, overridden: false, comparable: false,
  profile: { missing_pct: 0, n_distinct: 2, examples: [], levels: [] },
})
const VARS = [v('sex', 'categorical'), v('age', 'continuous'), v('grade', 'numeric-discrete')]

describe('explorer item-id filter (DB-04)', () => {
  test('case of an item id', () => {
    expect(caseOfItem('case_00001.01.voi.L')).toBe('case_00001')
    expect(caseOfItem('site.a.case_7.02.complete.-')).toBe('site.a.case_7')
  })

  test('cases holding a listed item, in list order', () => {
    const cases = [{ case_id: 'a' }, { case_id: 'b' }, { case_id: 'c' }]
    expect(filterByItems(cases, ['c.01.complete.-', 'a.01.voi.L', 'a.02.voi.R'])).toEqual([{ case_id: 'a' }, { case_id: 'c' }])
    expect(filterByItems(cases, undefined)).toBe(cases)
    expect(filterByItems(cases, [])).toEqual([])
  })

  test('store: set, dedupe, count as one filter, clear', () => {
    const s = useExplorer.getState()
    s.clearFilter()
    s.setFilter({ phase: 'NP' })
    s.setItemIds(['a.01.voi.L', 'a.01.voi.L', 'b.01.voi.R'])
    expect(useExplorer.getState().filter).toEqual({ phase: 'NP', itemIds: ['a.01.voi.L', 'b.01.voi.R'] })
    expect(activeFilterCount(useExplorer.getState().filter)).toBe(2)
    s.setItemIds(null)
    expect(useExplorer.getState().filter).toEqual({ phase: 'NP' })
    s.clearFilter()
  })
})

describe('Explorer filter → radiomics selection (RAD-05)', () => {
  test('phase and variable levels map; ranges and case-only criteria are dropped', () => {
    const x = explorerSelection({ q: 'case_1', phase: 'NP', status: 'accepted', vars: { sex: 'F', grade: '2', age: '40..60', empty: '' } }, VARS)
    expect(x).toEqual({ itemIds: null, scope: null, phase: ['NP'], vars: { sex: ['F'], grade: ['2'] }, ranges: ['age'], dropped: ['text', 'status'] })
  })

  test('an unknown variable with a range value counts as a range', () => {
    expect(explorerSelection({ vars: { gone: '1..2', lvl: 'x' } }, []).ranges).toEqual(['gone'])
  })

  test('an item list wins; its scope is kept when all items share one', () => {
    const x = explorerSelection({ phase: 'NP', vars: { sex: 'F' }, itemIds: ['a.01.voi.L', 'b.01.voi.R'] }, VARS)
    expect(x).toEqual({ itemIds: ['a.01.voi.L', 'b.01.voi.R'], scope: 'voi', phase: [], vars: {}, ranges: [], dropped: ['phase', 'vars'] })
    expect(explorerSelection({ itemIds: ['a.01.voi.L', 'a.01.complete.-'] }, VARS).scope).toBeNull()
  })
})
