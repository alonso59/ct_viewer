// @vitest-environment jsdom
// UI-10 (WCAG 2.2.1, 4.1.3): errors and warnings stay and are announced at once; info and success
// leave after 6 s unless hovered or focused; repeats merge with a count.
import { act, fireEvent, render, screen } from '@testing-library/react'

import '../i18n'
import { TOAST_MS, Toasts } from './Toasts'
import { toast, useWorkbench } from './workbenchStore'

beforeEach(() => {
  vi.useFakeTimers()
  useWorkbench.setState({ toasts: [] })
})
afterEach(() => vi.useRealTimers())

test('an error stays in the alert region; info leaves the status region after 6 s (UI-10)', () => {
  render(<Toasts />)
  act(() => {
    toast({ message: 'Could not save', tone: 'error' })
    toast({ message: 'Saved', tone: 'ok' })
  })
  expect(screen.getByRole('alert')).toHaveTextContent('Could not save')
  expect(screen.getByRole('status')).toHaveTextContent('Saved')
  act(() => vi.advanceTimersByTime(TOAST_MS + 100))
  expect(screen.getByRole('alert')).toHaveTextContent('Could not save')
  expect(screen.getByRole('status')).not.toHaveTextContent('Saved')
})

test('no empty alert region competes with error cards on the page (UI-10)', () => {
  render(<Toasts />)
  act(() => toast({ message: 'Saved', tone: 'ok' }))
  expect(screen.queryByRole('alert')).toBeNull()
})

test('hovering pauses the timer; leaving resumes it (UI-10)', () => {
  render(<Toasts />)
  act(() => toast({ message: 'Exported' }))
  const item = screen.getByText('Exported').closest('.toast')!
  act(() => vi.advanceTimersByTime(TOAST_MS - 1000))
  fireEvent.mouseEnter(item)
  act(() => vi.advanceTimersByTime(TOAST_MS * 3))
  expect(screen.getByText('Exported')).toBeInTheDocument()
  fireEvent.mouseLeave(item)
  act(() => vi.advanceTimersByTime(1100))
  expect(screen.queryByText('Exported')).toBeNull()
})

test('a repeat merges with a count, and errors are never evicted by info (UI-10)', () => {
  render(<Toasts />)
  act(() => {
    toast({ message: 'Hash failed', tone: 'error' })
    toast({ message: 'Hash failed', tone: 'error' })
    for (const n of [1, 2, 3, 4, 5]) toast({ message: `info ${n}` })
  })
  expect(screen.getAllByText('Hash failed')).toHaveLength(1)
  expect(screen.getByText('×2')).toBeInTheDocument()
  expect(useWorkbench.getState().toasts).toHaveLength(4)
  expect(screen.getByRole('alert')).toHaveTextContent('Hash failed')
})

test('Escape dismisses the focused toast (UI-10)', () => {
  render(<Toasts />)
  act(() => toast({ message: 'Disk full', tone: 'warn' }))
  fireEvent.keyDown(screen.getByRole('button', { name: 'Dismiss' }), { key: 'Escape' })
  expect(screen.queryByText('Disk full')).toBeNull()
})
