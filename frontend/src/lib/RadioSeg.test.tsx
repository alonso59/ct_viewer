// @vitest-environment jsdom
// FE-08 (radio groups, WAI-ARIA): a segmented choice is one radio group with one Tab stop on the
// checked option; arrow keys move the choice and the focus, wrapping; no toggle state on radios.
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import { RadioSeg } from './ui'

function Mode() {
  const [mode, setMode] = useState<'all' | 'filter' | 'list'>('all')
  return (
    <RadioSeg
      label="Items"
      value={mode}
      options={[
        { value: 'all', label: 'All' },
        { value: 'filter', label: 'Filter' },
        { value: 'list', label: 'List' },
      ]}
      onChange={setMode}
    />
  )
}

test('one Tab stop on the checked option; arrows move the choice and the focus (FE-08)', () => {
  render(<Mode />)
  expect(screen.getByRole('radiogroup', { name: 'Items' })).toBeInTheDocument()
  const all = screen.getByRole('radio', { name: 'All' })
  expect(all).toHaveAttribute('aria-checked', 'true')
  expect(all).not.toHaveAttribute('aria-pressed')
  expect(screen.getAllByRole('radio').map((r) => r.getAttribute('tabindex'))).toEqual(['0', '-1', '-1'])
  all.focus()
  fireEvent.keyDown(all, { key: 'ArrowRight' })
  const filter = screen.getByRole('radio', { name: 'Filter' })
  expect(filter).toHaveAttribute('aria-checked', 'true')
  expect(document.activeElement).toBe(filter)
  expect(filter).toHaveAttribute('tabindex', '0')
  fireEvent.keyDown(filter, { key: 'ArrowLeft' })
  fireEvent.keyDown(screen.getByRole('radio', { name: 'All' }), { key: 'ArrowLeft' })
  expect(screen.getByRole('radio', { name: 'List' })).toHaveAttribute('aria-checked', 'true')
  expect(document.activeElement).toBe(screen.getByRole('radio', { name: 'List' }))
})
