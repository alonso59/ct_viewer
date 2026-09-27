// UI-08 (AUD-A1-13): an item reads "case · phase · scope · side"; the raw item_id (DATA_MODEL
// §item_id) stays in the tooltip and in copy actions
import i18n from '../i18n'
import { itemName, parseItemId } from './itemName'

const t = i18n.t.bind(i18n)

test('parses item ids, also with dots in the case id', () => {
  expect(parseItemId('case_00055.01.complete.-')).toEqual({ case_id: 'case_00055', scan_idx: '01', scope: 'complete', side: '-' })
  expect(parseItemId('site.a.case_1.02.voi.L')).toEqual({ case_id: 'site.a.case_1', scan_idx: '02', scope: 'voi', side: 'L' })
  expect(parseItemId('not-an-item')).toBeNull()
})

test('names an item by case, phase (else scan), scope and side', () => {
  expect(itemName('case_00055.01.complete.-', t, 'NP')).toBe('case_00055 · NP · Full')
  expect(itemName('case_00055.01.voi.L', t, 'NP')).toBe('case_00055 · NP · VOI L')
  expect(itemName('case_00055.02.complete.-', t)).toBe('case_00055 · Scan 02 · Full')
  expect(itemName('odd', t)).toBe('odd')
})
