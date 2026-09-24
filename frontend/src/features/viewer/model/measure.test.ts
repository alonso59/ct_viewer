// VW-17 measurement math and VW-22/PRJ-14 window/modality helpers.
import { angleDeg, distanceMm } from './measure'
import { dicomWindowOf, effectiveModality } from './wl'

test('distance in mm and angle at the vertex', () => {
  expect(distanceMm([0, 0, 0], [3, 4, 0])).toBe(5)
  expect(angleDeg([1, 0, 0], [0, 0, 0], [0, 1, 0])).toBeCloseTo(90)
  expect(angleDeg([1, 0, 0], [0, 0, 0], [1, 1, 0])).toBeCloseTo(45)
  expect(angleDeg([0, 0, 0], [0, 0, 0], [1, 0, 0])).toBe(0) // degenerate
})

test('DICOM header window from row facts (strings) or Open-mode numbers', () => {
  expect(dicomWindowOf({ extra: { window_width: '400', window_center: '40' } })).toEqual([400, 40])
  expect(dicomWindowOf({ extra: { window_width: 1500, window_center: -600 } })).toEqual([1500, -600])
  expect(dicomWindowOf({ extra: { window_width: '', window_center: '' } })).toBeNull()
  expect(dicomWindowOf({ extra: {} })).toBeNull()
})

test('an unknown modality falls back to the project default (PRJ-14)', () => {
  const item = { item_id: 'a', case_id: 'c', image: null, modality: null }
  expect(effectiveModality(item, {})).toEqual({ value: 'CT', assumed: true })
  expect(effectiveModality(item, {}, 'MR')).toEqual({ value: 'MR', assumed: true })
  expect(effectiveModality(item, {}, 'mixed')).toEqual({ value: 'CT', assumed: true })
  expect(effectiveModality({ ...item, modality: 'CT' }, {}, 'MR')).toEqual({ value: 'CT', assumed: false })
})
