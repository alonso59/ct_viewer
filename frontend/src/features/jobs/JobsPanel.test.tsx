// @vitest-environment jsdom
// UI-29 / FE-09: the Activity channel survives new lines even where scrollIntoView returns a Promise.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'

import '../../i18n'
import { keys, type Job } from '../../api'
import { useWorkbench } from '../../shell'
import { ActivityLog, JobStatus, JobsPanel, logEvent } from './JobsPanel'

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

// UI-07: the status bar counts background work; a single running job keeps its progress
test('running, queued and waiting jobs read as counts (UI-07)', () => {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  const job = (status: Job['status'], n: number) => ({ job_id: `j${n}`, kind: 'hash', status, done: 1, total: 4, eta_s: null, error: null }) as unknown as Job
  qc.setQueryData(keys.jobs('P1'), [job('running', 1), job('queued', 2), job('queued', 3), job('waiting_for_runner', 4)])
  useWorkbench.setState({ pid: 'P1' })
  render(<QueryClientProvider client={qc}><JobStatus /></QueryClientProvider>)
  expect(screen.getByRole('button', { name: '1 running · 2 queued · 1 waiting for a runner' })).toBeInTheDocument()
})

// UI-10: one event, one primary channel; the Jobs row repeats a failure as text, not as another alert
test('a failed job shows its error as text, not as another alert (UI-10)', () => {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  qc.setQueryData(keys.jobs('P1'), [{ job_id: 'j1', kind: 'hash', status: 'failed', done: 1, total: 4, eta_s: null, error: 'Disk full' } as unknown as Job])
  useWorkbench.setState({ pid: 'P1' })
  render(<QueryClientProvider client={qc}><JobsPanel /></QueryClientProvider>)
  expect(screen.getByText('Disk full')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).toBeNull()
})
