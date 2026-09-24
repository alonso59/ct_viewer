// RAD-05 run selection
import { criteriaCount, emptySelection, knownEmpty, parseItemIds, toFilter, toSelection, type SelectionForm } from './selection'

const sel = (p: Partial<SelectionForm> = {}): SelectionForm => ({ ...emptySelection([3, 1, 2]), ...p })

describe('toSelection', () => {
  test('all mode: scope and sorted labels only', () => {
    expect(toSelection(sel({ phase: ['NP'], list: 'a b' }))).toEqual({ scope: 'complete', labels: [1, 2, 3] })
  })

  test('labels sorted numerically without mutating the form', () => {
    const s = sel({ labels: [10, 2, 1] })
    expect(toSelection(s).labels).toEqual([1, 2, 10])
    expect(s.labels).toEqual([10, 2, 1])
  })

  test('filter mode drops empty criteria', () => {
    const s = sel({ mode: 'filter', scope: 'voi', phase: ['NP', 'AP'], side: [], vars: { grade: ['G1'], site: [] } })
    expect(toSelection(s)).toEqual({ scope: 'voi', labels: [1, 2, 3], filter: { phase: ['NP', 'AP'], var: { grade: ['G1'] } } })
  })

  test('filter mode with no criteria has no filter', () => {
    expect(toSelection(sel({ mode: 'filter', vars: { site: [] } }))).toEqual({ scope: 'complete', labels: [1, 2, 3] })
    expect(toFilter(sel({ mode: 'filter' }))).toBeNull()
  })

  test('list mode: deduplicated ids', () => {
    expect(toSelection(sel({ mode: 'list', list: 'a, b\nc;a  b\n' }))).toEqual({ scope: 'complete', labels: [1, 2, 3], item_ids: ['a', 'b', 'c'] })
  })

  test('list mode with empty text sends an empty list', () => {
    expect(toSelection(sel({ mode: 'list', list: '  ' })).item_ids).toEqual([])
  })
})

describe('parseItemIds', () => {
  test.each<[string, string[]]>([
    ['', []],
    ['  \n ', []],
    ['a', ['a']],
    ['a,b;c d\te\nf', ['a', 'b', 'c', 'd', 'e', 'f']],
    ['x, x ,x', ['x']],
    ['b a b', ['b', 'a']],
  ])('%j', (text, ids) => {
    expect(parseItemIds(text)).toEqual(ids)
  })
})

describe('knownEmpty', () => {
  test('only an explicit list with no ids', () => {
    expect(knownEmpty(sel({ mode: 'list', list: ' , ' }))).toBe(true)
    expect(knownEmpty(sel({ mode: 'list', list: 'a' }))).toBe(false)
    expect(knownEmpty(sel({ mode: 'all' }))).toBe(false)
    expect(knownEmpty(sel({ mode: 'filter' }))).toBe(false)
  })
})

describe('criteriaCount', () => {
  test('counts phase, side and each non-empty variable', () => {
    expect(criteriaCount(sel())).toBe(0)
    expect(criteriaCount(sel({ phase: ['NP'] }))).toBe(1)
    expect(criteriaCount(sel({ phase: ['NP', 'AP'], side: ['L', 'R'] }))).toBe(2)
    expect(criteriaCount(sel({ phase: ['NP'], side: ['-'], vars: { a: ['1'], b: ['x', 'y'], c: [] } }))).toBe(4)
  })
})

test('emptySelection defaults', () => {
  expect(emptySelection()).toEqual({ mode: 'all', scope: 'complete', labels: [], phase: [], side: [], vars: {}, list: '' })
})
