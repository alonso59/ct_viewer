// @vitest-environment jsdom
// UI-29: the log view follows new lines until the user scrolls up, filters levels and copies.
import '../../i18n'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import type { LogLine } from '../../api'
import { LogView } from './LogView'

afterEach(cleanup)

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
  const view = render(<LogView lines={lines.slice(0, 1)} />)
  const log = screen.getByRole('log')
  expect(log.getAttribute('aria-live')).toBe('polite')
  geometry(log, 500)
  view.rerender(<LogView lines={lines.slice(0, 2)} />)
  expect(log.scrollTop).toBe(500)

  log.scrollTop = 100
  fireEvent.scroll(log)
  geometry(log, 800)
  view.rerender(<LogView lines={lines} />)
  expect(log.scrollTop).toBe(100)

  fireEvent.click(screen.getByRole('button', { name: /jump to latest/i }))
  expect(log.scrollTop).toBe(800)
  expect(screen.queryByRole('button', { name: /jump to latest/i })).toBeNull()
})

test('filters by level', () => {
  render(<LogView lines={lines} />)
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
  render(<LogView lines={lines} />)
  fireEvent.click(screen.getByRole('button', { name: 'Errors' }))
  await act(async () => fireEvent.click(screen.getByRole('button', { name: /copy/i })))
  expect(writeText).toHaveBeenCalledWith('OSError: DATA:')
})
