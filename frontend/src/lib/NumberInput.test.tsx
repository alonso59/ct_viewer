// AUD-A3-04 (owner 2026-09-25): number fields show a point and accept `,` or `.` on every machine
import { fireEvent, render, screen } from '@testing-library/react'

import { NumberInput } from './ui'

test('typing a comma or a point gives the same number; arrows step within bounds', () => {
  const got: (number | null)[] = []
  render(<NumberInput aria-label="Threshold" value={3.5} step={0.5} min={1} max={4} onChange={(n) => got.push(n)} />)
  const input = screen.getByRole('spinbutton', { name: 'Threshold' })
  expect(input).toHaveValue('3.5')
  expect(input).toHaveAttribute('inputmode', 'decimal')
  fireEvent.change(input, { target: { value: '2,5' } })
  fireEvent.change(input, { target: { value: '2.5' } })
  expect(got).toEqual([2.5, 2.5])
  expect(input).toHaveValue('2.5')
  fireEvent.keyDown(input, { key: 'ArrowUp' })
  fireEvent.keyDown(input, { key: 'ArrowUp' })
  fireEvent.keyDown(input, { key: 'ArrowUp' })
  expect(got.slice(2)).toEqual([3, 3.5, 4])
  fireEvent.change(input, { target: { value: 'x' } })
  expect(got.at(-1)).toBeNull()
  expect(input).toHaveAttribute('aria-invalid', 'true')
})
