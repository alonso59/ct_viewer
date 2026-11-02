// @vitest-environment jsdom
// UI-29 / FE-09: the Activity channel survives new lines even where scrollIntoView returns a Promise.
import { act, render, screen } from '@testing-library/react'

import '../../i18n'
import { ActivityLog, logEvent } from './JobsPanel'

test('new Activity lines and unmount do not throw when scrollIntoView returns a Promise (UI-29)', () => {
  Element.prototype.scrollIntoView = vi.fn(() => Promise.resolve()) as unknown as typeof Element.prototype.scrollIntoView
  const index = (n: number) => ({ event: 'index.rebuilt', data: { n_items: n, n_warnings: 0 } }) as Parameters<typeof logEvent>[0]
  act(() => logEvent(index(1)))
  const { unmount } = render(<ActivityLog />)
  act(() => logEvent(index(2)))
  act(() => logEvent(index(3)))
  expect(screen.getAllByText(/3 items|items/).length).toBeGreaterThan(0)
  expect(() => unmount()).not.toThrow()
})
