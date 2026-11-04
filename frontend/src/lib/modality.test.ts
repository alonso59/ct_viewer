// VW-05 / VW-11: an item's modality as the GUI names it.
import type { TFunction } from 'i18next'

import { effectiveModality, modalityText, namedComponent } from './modality'

const names: Record<string, string> = { 'viewer.modality.OT': 'Other', 'viewer.component.PHASE': 'Phase' }
const t = ((key: string, o?: { defaultValue?: string }) => names[key] ?? o?.defaultValue ?? key) as unknown as TFunction

test('the badge text is the DICOM code, plus the MR component unless it is magnitude', () => {
  expect(modalityText(t, 'CT')).toBe('CT')
  expect(modalityText(t, 'MR', 'PHASE')).toBe('MR · Phase')
  expect(modalityText(t, 'MR', 'IMAGINARY')).toBe('MR · IMAGINARY') // untranslated code still shows
  expect(modalityText(t, 'OT')).toBe('Other')
  expect(namedComponent({ image_component: 'MAGNITUDE' })).toBeNull()
  expect(namedComponent({ image_component: 'PHASE' })).toBe('PHASE')
  expect(namedComponent({ image_component: null })).toBeNull()
})

test('a known modality is upper-cased and never assumed', () => {
  const item = { item_id: 'a', case_id: 'c', image: null, modality: 'mr' }
  expect(effectiveModality(item, {}, 'CT')).toEqual({ value: 'MR', assumed: false })
})
