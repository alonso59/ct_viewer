// @vitest-environment jsdom
// VW-08 / VW-22 (AUD-A2-11, AUD-A3-05): one readout: value with its unit, label name, ijk, RAS mm.
import i18n from '../../i18n'
import { cursorParts } from './readout'

const t = i18n.t.bind(i18n)
const c = { ijk: [29, 31, 24] as [number, number, number], ras: [31.2, 29.2, 36] as [number, number, number], value: 35, label: 1, labelName: 'kidney' }

test('CT shows HU, the label by name, ijk and RAS mm', () => {
  expect(cursorParts(c, { modality: 'CT' }, t).join(' · ')).toBe('35 HU · kidney (1) · ijk 29, 31, 24 · RAS 31.2, 29.2, 36 mm')
  // unknown modality is assumed CT (VW-05)
  expect(cursorParts(c, { modality: null }, t)[0]).toBe('35 HU')
})

test('MR shows a plain value; an unnamed label and no label', () => {
  expect(cursorParts({ ...c, labelName: undefined }, { modality: 'MR' }, t).slice(0, 2)).toEqual(['value 35', 'label 1 (1)'])
  expect(cursorParts({ ...c, label: 0 }, { modality: 'CT', emptyLabel: true }, t)[1]).toBe('label —')
  expect(cursorParts({ ...c, label: 0 }, { modality: 'CT' }, t)).toHaveLength(3)
})
