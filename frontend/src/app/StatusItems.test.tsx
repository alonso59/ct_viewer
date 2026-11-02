// @vitest-environment jsdom
// UI-07: after 10 s without the event stream the status bar says updates are paused and offers a refresh.
import { act, render, screen } from '@testing-library/react'

import '../i18n'
import { useConnection } from '../api'
import { LiveStatus } from './StatusItems'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

test('a dropped stream reads "connecting" first, then "updates paused" with a refresh button (UI-07)', () => {
  act(() => useConnection.getState().set('live'))
  render(<LiveStatus />)
  expect(screen.getByText('live')).toBeInTheDocument()
  act(() => useConnection.getState().set('connecting'))
  expect(screen.getByText('connecting')).toBeInTheDocument()
  act(() => vi.advanceTimersByTime(10_500))
  expect(screen.getByRole('button', { name: /offline: updates paused/ })).toBeInTheDocument()
  act(() => useConnection.getState().set('live'))
  expect(screen.getByText('live')).toBeInTheDocument()
})
