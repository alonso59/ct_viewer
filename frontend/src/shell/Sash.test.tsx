// @vitest-environment jsdom
// UI-13: a sash is a focusable separator with its size as a value; arrow keys resize, Enter resets
import { fireEvent, render, screen } from '@testing-library/react'

import { SASH_STEP, Sash } from './Sash'

test('arrows resize like a drag in their direction, Enter restores the default', () => {
  const onStart = vi.fn()
  const onDrag = vi.fn()
  const onReset = vi.fn()
  render(<Sash direction="v" label="Resize the side bar" value={300} min={200} max={640} onStart={onStart} onDrag={onDrag} onReset={onReset} />)
  const sash = screen.getByRole('separator', { name: 'Resize the side bar' })
  expect(sash).toHaveAttribute('tabindex', '0')
  expect(sash).toHaveAttribute('aria-valuenow', '300')
  expect(sash).toHaveAttribute('aria-valuemin', '200')
  expect(sash).toHaveAttribute('aria-valuemax', '640')
  fireEvent.keyDown(sash, { key: 'ArrowRight' })
  expect(onStart).toHaveBeenCalledOnce()
  expect(onDrag).toHaveBeenLastCalledWith(SASH_STEP)
  fireEvent.keyDown(sash, { key: 'ArrowLeft' })
  expect(onDrag).toHaveBeenLastCalledWith(-SASH_STEP)
  // a vertical sash ignores up and down
  fireEvent.keyDown(sash, { key: 'ArrowUp' })
  expect(onDrag).toHaveBeenCalledTimes(2)
  fireEvent.keyDown(sash, { key: 'Enter' })
  expect(onReset).toHaveBeenCalledOnce()
})
