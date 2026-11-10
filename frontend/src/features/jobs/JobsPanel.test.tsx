// @vitest-environment jsdom
// UI-29 / FE-09: the Activity channel survives new lines even where scrollIntoView returns a Promise.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import '../../i18n'
import { api, keys, type Job } from '../../api'
import { useWorkbench } from '../../shell'
import { ActivityLog, JobStatus, JobsPanel, logEvent } from './JobsPanel'

// jsdom lays nothing out: the virtualised list needs a size to render its rows (prototype
// properties, so restoring mocks between tests keeps them)
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', { configurable: true, value: () => ({ width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => ({}) }) })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 600 })
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get: () => 800 })
})

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

test('the panel shows loading, then a retryable error, before the empty state', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  qc.setQueryData(keys.tasks(), { tasks: [] })
  useWorkbench.setState({ pid: 'P1' })
  const list = vi.spyOn(api, 'listJobs').mockRejectedValue(new TypeError('offline'))
  render(<QueryClientProvider client={qc}><JobsPanel /></QueryClientProvider>)
  expect(screen.getByText('Loading…')).toBeInTheDocument()
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(screen.queryByText('No jobs')).toBeNull()
  list.mockResolvedValue([])
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByText('No jobs')).toBeInTheDocument()
})

test('a running task job is cancellable by name, a queued one only from its run, and a failed cancel is reported', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  const job = { job_id: 'j1', kind: 'task', key: 'nnunet', status: 'running', done: 0, total: 4, eta_s: null, error: null } as unknown as Job
  const queued = { ...job, job_id: 'j2', status: 'queued' } as Job
  qc.setQueryData(keys.jobs('P1'), [job, queued])
  qc.setQueryData(keys.tasks(), { tasks: [{ manifest: { id: 'nnunet', title: 'Segment kidneys' } }] })
  useWorkbench.setState({ pid: 'P1', toasts: [] })
  vi.spyOn(api, 'cancelJob').mockRejectedValue(new Error('cancel refused'))
  render(<QueryClientProvider client={qc}><JobsPanel /></QueryClientProvider>)
  expect(screen.getByRole('columnheader', { name: 'Actions' })).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Cancel Segment kidneys' })).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Cancel Segment kidneys' }))
  fireEvent.click(screen.getByRole('button', { name: 'Yes, cancel' }))
  await waitFor(() => expect(useWorkbench.getState().toasts).toHaveLength(1))
})
