// ADR-0057: a case's scans grouped by DICOM exam → series → part, display only.
import i18n from '../i18n'
import type { ItemRecord } from '../api'
import { groupScans, scanGroupLabel, type GroupedScan } from './scanGroups'

const t = i18n.t.bind(i18n)

function scan(idx: string, extra: Record<string, unknown>, scope: ItemRecord['scope'] = 'complete'): ItemRecord {
  return {
    item_id: `c.${idx}.${scope}.-`, case_id: 'c', scan_idx: idx, scope, side: '-', status: 'active',
    phase: { canonical: 'UNK', raw: null, source: 'none' }, image: { path: '', fp: '' }, masks: {}, labels_present: [],
    import_id: 'i', extra: scope === 'voi' ? {} : extra,
  } as unknown as ItemRecord
}
const order = (g: GroupedScan[]) => g.map((s) => s.scanIdx)
const labels = (g: GroupedScan[]) => g.map((s) => s.groups.map((x) => scanGroupLabel(t, x)).join(' / '))

test('MR: parts of one series stay together, unsuffixed first; the ADC follows its DWI by series number', () => {
  const ex = { study_uid: 'S1', days_from_first_scan: '0' }
  const g = groupScans([
    scan('205', { ...ex, series_uid: 'D#t4', series_number: '7' }),
    scan('155', { ...ex, series_uid: 'D', series_number: '7', series_description: 'e-THRIVE_dyn_BH' }),
    scan('203', { ...ex, series_uid: 'D#t2', series_number: '7' }),
    scan('204', { ...ex, series_uid: 'D#t3', series_number: '7' }),
    scan('144', { ...ex, series_uid: 'A', series_number: '10' }),
    scan('145', { ...ex, series_uid: 'W', series_number: '9' }),
    scan('146', { ...ex, series_uid: 'W#b800.0', series_number: '9' }),
  ])
  expect(order(g)).toEqual(['155', '203', '204', '205', '145', '146', '144'])
  expect(g.map((s) => s.part)).toEqual([null, 't2', 't3', 't4', null, 'b800', null])
  // one exam: no exam level; a one-part series (the ADC): no series level
  expect(labels(g)).toEqual([...Array(4).fill('Series 7 · e-THRIVE_dyn_BH'), 'Series 9', 'Series 9', ''])
})

test('CT: exams in day order, one-volume series left out, two exams on one day numbered', () => {
  const g = groupScans([
    scan('05', { study_uid: 'B', days_from_first_scan: '84', series_uid: 'x5' }),
    scan('01', { study_uid: 'A', days_from_first_scan: '0', series_uid: 'x1', series_number: '2' }),
    scan('02', { study_uid: 'A', days_from_first_scan: '0', series_uid: 'x2', series_number: '1' }),
    scan('09', { study_uid: 'C', days_from_first_scan: '84', series_uid: 'x9' }),
  ])
  expect(order(g)).toEqual(['02', '01', '05', '09'])
  expect(labels(g)).toEqual(['Exam · day 0', 'Exam · day 0', 'Exam · day 84 (1)', 'Exam · day 84 (2)'])
})

test('without days, exams follow their lowest scan and are numbered', () => {
  const g = groupScans([scan('03', { study_uid: 'Z' }), scan('01', { study_uid: 'Y' })])
  expect(order(g)).toEqual(['01', '03'])
  expect(labels(g)).toEqual(['Exam 1', 'Exam 2'])
})

test('a case without exam facts stays flat in scan order; scans without one go last', () => {
  expect(groupScans([scan('10', {}), scan('2', {})]).map((s) => [s.scanIdx, s.groups.length])).toEqual([['2', 0], ['10', 0]])
  const g = groupScans([scan('1', {}), scan('2', { study_uid: 'A' })])
  expect(order(g)).toEqual(['2', '1'])
  // the one exam still shows, to set its scans apart from the others
  expect(labels(g)).toEqual(['Exam 1', 'Other scans'])
})

test('VOI items take the facts of their full-volume item', () => {
  const g = groupScans([scan('2', {}, 'voi'), scan('2', { study_uid: 'A', series_uid: 'S#e2' }), scan('1', { study_uid: 'B' })])
  const two = g.find((s) => s.scanIdx === '2')!
  expect(two.items).toHaveLength(2)
  expect(two.part).toBe('e2')
  expect(two.groups[0]).toMatchObject({ kind: 'exam', uid: 'A' })
})
