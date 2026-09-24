// VW-19: a task set's values are coloured by the project labels they map to (ADR-0015 mapping).
import type { LabelDef } from '../../api'
import { setLabels } from './CaseEditor'

const L = (value: number, name: string): LabelDef => ({ value, name, color: `#00000${value}`, opacity: 0.2, visible: true })

test('identity or empty mapping keeps the label map; a mapping re-keys by set value', () => {
  const labels = [L(1, 'kidney'), L(2, 'tumor'), L(4, 'foreground')]
  expect(setLabels(labels, undefined)).toBe(labels)
  expect(setLabels(labels, { '1': 1, '2': 2 })).toBe(labels)
  expect(setLabels(labels, { '1': 4 })).toEqual([{ ...L(4, 'foreground'), value: 1 }])
  expect(setLabels(labels, { '1': 9 })).toEqual([])
})
