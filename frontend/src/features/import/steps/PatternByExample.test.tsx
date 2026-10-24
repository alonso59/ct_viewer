// @vitest-environment jsdom
// SRC-17 pattern by example: marking the case on a real path writes the pattern; a picked mask
// shows as this image's mask, and masks under the template leave the sample count.
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import '../../../i18n/lazy'
import type { NiftiOptions } from '../../../api'
import { PatternByExample } from './PatternByExample'

const PANTS = ['ImageTr/P_001/ct', 'ImageTr/P_002/ct', 'LabelTr/P_001/segmentations/liver', 'LabelTr/P_002/segmentations/liver']

function Host({ start, seen }: { start: NiftiOptions; seen: (o: NiftiOptions) => void }) {
  const [value, setValue] = useState(start)
  return (
    <PatternByExample
      root="/data/pants"
      stems={PANTS}
      value={value}
      onChange={(o) => {
        seen(o)
        setValue(o)
      }}
    />
  )
}

test('marking the case folder builds the pattern and checks it on the sample', () => {
  let last: NiftiOptions = {}
  render(<Host start={{}} seen={(o) => (last = o)} />)
  expect(screen.getByRole('status')).toHaveTextContent('No part is marked as the case yet')
  fireEvent.change(screen.getByRole('combobox', { name: 'What ImageTr is' }), { target: { value: 'fixed' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'What P_001 is' }), { target: { value: 'case_id' } })
  expect(last.pattern).toBe('^ImageTr/(?P<case_id>[^/]+)/ct$')
  // the label files do not follow the example yet: no mask template
  expect(screen.getByRole('status')).toHaveTextContent('2 of 4 sampled images follow this example')
})

test('with a mask template the example shows its mask and masks leave the count', () => {
  render(<Host start={{ pattern: '^ImageTr/(?P<case_id>[^/]+)/ct$', mask_template: 'LabelTr/{case_id}/segmentations' }} seen={() => undefined} />)
  expect(screen.getByRole('combobox', { name: 'What P_001 is' })).toHaveValue('case_id')
  expect(screen.getByRole('status')).toHaveTextContent('2 of 2 sampled images follow this example')
  expect(screen.getByText('LabelTr/P_001/segmentations')).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: 'Example image' }).querySelectorAll('option')).toHaveLength(2)
})
