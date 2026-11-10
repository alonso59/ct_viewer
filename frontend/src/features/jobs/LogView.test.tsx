// @vitest-environment jsdom
// UI-29: one log view for every channel: it follows new lines until the user scrolls up, filters
// levels and text, copies and downloads the lines shown, and shows loading, error and ended states.
import '../../i18n'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, expect, test, vi } from 'vitest'

import type { LogLine } from '../../api'
import { useWorkbench } from '../../shell'
import { LogView } from './LogView'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  useWorkbench.setState({ toasts: [] })
})

// jsdom lays nothing out: the virtualised list needs a size to render its rows (prototype
// properties, so restoring mocks between tests keeps them)
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', { configurable: true, value: () => ({ width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => ({}) }) })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 600 })
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get: () => 800 })
})

const lines: LogLine[] = [
  { ts: null, level: 'info', stream: 'stage', text: 'reading 1/2' },
  { ts: null, level: 'warn', stream: 'log', text: 'slow disk' },
  { ts: null, level: 'error', stream: 'stderr', text: 'OSError: DATA:' },
]

/** jsdom has no layout: give the list a fixed geometry */
function geometry(el: HTMLElement, scrollHeight: number) {
  Object.defineProperty(el, 'scrollHeight', { configurable: true, value: scrollHeight })
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: 100 })
}

test('follows new lines, pauses when scrolled up and jumps back to the latest', () => {
  const view = render(<LogView lines={lines.slice(0, 1)} name="run" />)
  const log = screen.getByRole('log')
  expect(log).not.toHaveAttribute('aria-live')
  expect(log).toHaveAttribute('tabindex', '0')
  geometry(log, 500)
  view.rerender(<LogView lines={lines.slice(0, 2)} name="run" />)
  expect(log.scrollTop).toBe(500)

  log.scrollTop = 100
  fireEvent.scroll(log)
  geometry(log, 800)
  view.rerender(<LogView lines={lines} name="run" />)
  expect(log.scrollTop).toBe(100)

  fireEvent.click(screen.getByRole('button', { name: /jump to latest/i }))
  expect(log.scrollTop).toBe(800)
  expect(screen.queryByRole('button', { name: /jump to latest/i })).toBeNull()
})

test('filters by level', () => {
  render(<LogView lines={lines} name="run" />)
  const log = screen.getByRole('log')
  expect(log.textContent).toContain('reading 1/2')
  fireEvent.click(screen.getByRole('button', { name: 'Warnings' }))
  expect(log.textContent).not.toContain('reading')
  expect(log.textContent).toContain('slow disk')
  fireEvent.click(screen.getByRole('button', { name: 'Errors' }))
  expect(log.textContent).toBe('OSError: DATA:')
})

test('copies the shown lines', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  render(<LogView lines={lines} name="run" />)
  fireEvent.click(screen.getByRole('button', { name: 'Errors' }))
  await act(async () => fireEvent.click(screen.getByRole('button', { name: /copy/i })))
  expect(writeText).toHaveBeenCalledWith('OSError: DATA:')
})

test('a text filter narrows the lines and says when none match', () => {
  render(<LogView lines={lines} name="run" />)
  const log = screen.getByRole('log')
  fireEvent.change(screen.getByRole('searchbox', { name: 'Filter lines' }), { target: { value: 'disk' } })
  expect(log.textContent).toBe('slow disk')
  fireEvent.change(screen.getByRole('searchbox', { name: 'Filter lines' }), { target: { value: 'nothing like this' } })
  expect(log).toHaveTextContent('No line matches the filter')
})

test('Copy says how many of how many lines it took', async () => {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } })
  render(<LogView lines={lines} name="run" />)
  fireEvent.click(screen.getByRole('button', { name: 'Warnings' }))
  await act(async () => fireEvent.click(screen.getByRole('button', { name: /copy/i })))
  expect(useWorkbench.getState().toasts.at(-1)?.message).toBe('Copied 2 of 3 lines (filtered)')
  fireEvent.click(screen.getByRole('button', { name: 'All' }))
  await act(async () => fireEvent.click(screen.getByRole('button', { name: /copy/i })))
  expect(useWorkbench.getState().toasts.at(-1)?.message).toBe('Copied 3 lines')
})

test('Download saves the lines shown as a .log file made in the browser', async () => {
  const blobs: Blob[] = []
  const names: string[] = []
  URL.createObjectURL = vi.fn((b: Blob) => {
    blobs.push(b)
    return 'blob:log'
  })
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    names.push(this.download)
  })
  render(<LogView lines={lines} name="ds · output" />)
  fireEvent.click(screen.getByRole('button', { name: 'Errors' }))
  fireEvent.click(screen.getByRole('button', { name: 'Download' }))
  expect(names).toEqual(['ds_output.log'])
  expect(await blobs[0]!.text()).toBe('OSError: DATA:\n')
})

test('loading, a failed fetch with Try again, and the end of the log are shown', () => {
  const retry = vi.fn()
  const view = render(<LogView lines={[]} name="run" loading />)
  expect(screen.getByRole('log')).toHaveTextContent('Loading')
  view.rerender(<LogView lines={[]} name="run" error={new Error('The server did not answer')} onRetry={retry} />)
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(retry).toHaveBeenCalled()
  view.rerender(<LogView lines={lines} name="run" ended redacted />)
  expect(screen.getByRole('log')).toHaveTextContent('Log ended')
  expect(screen.getByText('Host paths are redacted')).toBeInTheDocument()
})
