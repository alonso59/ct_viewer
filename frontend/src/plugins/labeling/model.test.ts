// LBL-03 spreadsheet helpers: paste, fill, navigation, filter, sort.
import type { LabelCellRow, LabelColumn } from '../../api'
import { display, fillCells, filterRows, move, parseTsv, pasteCells, sortRows } from './model'

const col = (id: string, type: LabelColumn['type'], extra: Partial<LabelColumn> = {}): LabelColumn => ({ column_id: id, slug: id, name: id, type, levels: [], unit: null, min: null, max: null, description: '', default: null, hidden: false, ...extra })
const cols = [col('a', 'category', { levels: ['G1', 'G2'] }), col('b', 'number', { unit: 'mm' }), col('c', 'bool')]
const rows: LabelCellRow[] = ['c1', 'c2', 'c3'].map((t, i) => ({ target: t, case_id: t, item_id: null, values: i === 1 ? { a: 'G2', b: 5, c: true } : {}, updated: {} }))

test('paste a TSV block from a spreadsheet at the active cell, clipped to the table', () => {
  const grid = parseTsv('G1\t10\r\nG2\t\t\tbeyond\n')
  expect(grid).toEqual([['G1', '10'], ['G2', '', '', 'beyond']])
  expect(pasteCells(grid, { r: 1, c: 0 }, rows, cols)).toEqual([
    { column_id: 'a', target: 'c2', value: 'G1' },
    { column_id: 'b', target: 'c2', value: '10' },
    { column_id: 'a', target: 'c3', value: 'G2' },
    { column_id: 'b', target: 'c3', value: null },
    { column_id: 'c', target: 'c3', value: null },
  ])
})

test('bulk fill a selection in any drag direction', () => {
  expect(fillCells({ r: 2, c: 1 }, { r: 1, c: 0 }, 'x', rows, cols).map((x) => `${x.target}:${x.column_id}`)).toEqual(['c2:a', 'c2:b', 'c3:a', 'c3:b'])
})

test('keyboard moves stay inside the grid', () => {
  expect(move({ r: 0, c: 0 }, 'ArrowUp', 3, 3)).toEqual({ r: 0, c: 0 })
  expect(move({ r: 2, c: 2 }, 'ArrowRight', 3, 3)).toEqual({ r: 2, c: 2 })
  expect(move({ r: 0, c: 1 }, 'Enter', 3, 3)).toEqual({ r: 1, c: 1 })
})

test('display, filter ("-" = empty) and sort', () => {
  expect(display(cols[1]!, 5)).toBe('5 mm')
  expect(display(cols[2]!, false)).toBe('✗')
  expect(filterRows(rows, cols, { a: 'g2' }, '').map((r) => r.target)).toEqual(['c2'])
  expect(filterRows(rows, cols, { a: '-' }, '').map((r) => r.target)).toEqual(['c1', 'c3'])
  expect(filterRows(rows, cols, {}, 'c3').map((r) => r.target)).toEqual(['c3'])
  expect(sortRows(rows, 'b', -1)[0]!.target).toBe('c2') // empty values last
  expect(sortRows(rows, '__target', -1).map((r) => r.target)).toEqual(['c3', 'c2', 'c1'])
})
