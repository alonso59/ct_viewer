// @vitest-environment jsdom
// FE-08 (live-region budget): one shared polite region; at most one announcement per 3 s; a newer
// message replaces one still waiting; the same words again are read again.
import { act, render, screen } from '@testing-library/react'

import { ANNOUNCE_GAP_MS, Announcer, announce, useAnnouncer } from './announce'

beforeEach(() => {
  vi.useFakeTimers()
  useAnnouncer.setState({ text: '', pending: null, last: -Infinity, timer: null })
})
afterEach(() => vi.useRealTimers())

test('a burst coalesces to its last message, then one per gap (FE-08)', () => {
  render(<Announcer />)
  const region = screen.getByRole('status')
  expect(region).toHaveAttribute('aria-live', 'polite')
  act(() => {
    announce('Convert DICOM: Reading headers')
    announce('Convert DICOM: Planning')
  })
  act(() => vi.advanceTimersByTime(0))
  expect(region).toHaveTextContent('Convert DICOM: Planning')
  act(() => announce('Convert DICOM: Converting'))
  act(() => vi.advanceTimersByTime(ANNOUNCE_GAP_MS - 1))
  expect(region).toHaveTextContent('Convert DICOM: Planning')
  act(() => announce('Convert DICOM: Completed'))
  act(() => vi.advanceTimersByTime(1))
  expect(region).toHaveTextContent('Convert DICOM: Completed')
})

test('the same words twice still change the region (FE-08)', () => {
  render(<Announcer />)
  act(() => announce('Volume loaded'))
  act(() => vi.advanceTimersByTime(0))
  const first = screen.getByRole('status').textContent
  act(() => announce('Volume loaded'))
  act(() => vi.advanceTimersByTime(ANNOUNCE_GAP_MS))
  expect(screen.getByRole('status').textContent).not.toBe(first)
  expect(screen.getByRole('status')).toHaveTextContent('Volume loaded')
})
