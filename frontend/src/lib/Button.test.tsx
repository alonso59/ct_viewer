// @vitest-environment jsdom
// UI-18 / UI-05: a disabled action says why (tooltip and accessible description); an enabled one does not.
import { render, screen } from '@testing-library/react'

import '../i18n'
import { Button } from './ui'

test('a disabled button carries its reason as title and description (UI-18)', () => {
  render(<Button className="btn" disabled reason="Choose a folder first">{'Next'}</Button>)
  const next = screen.getByRole('button', { name: 'Next' })
  expect(next).toBeDisabled()
  expect(next).toHaveAttribute('title', 'Choose a folder first')
  expect(next).toHaveAccessibleDescription('Choose a folder first')
})

test('an enabled button shows no reason (UI-18)', () => {
  render(<Button className="btn" reason="Choose a folder first">{'Next'}</Button>)
  expect(screen.getByRole('button', { name: 'Next' })).not.toHaveAttribute('title')
  expect(screen.queryByText('Choose a folder first')).toBeNull()
})
