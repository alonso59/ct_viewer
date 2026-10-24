// @vitest-environment jsdom
// TSK-15 / U1: a run waiting for verified cleanup says so (never "Failed" or "Completed"), and its
// actions call the supervised controls; view-only links show no mutation.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { api, type TaskRunSummary } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { registry } from '../../shell'
import { RunRow } from './TaskEditor'

afterEach(() => {
  vi.restoreAllMocks()
  registry.setReadOnly(false)
})

const base = {
  run_id: '01J00000000000000000000000',
  task: { id: 'segment.nnunet', version: '1.0.0', manifest_hash: 'x' },
  name: 'nnU-Net run',
  created_at: '2026-10-22T10:00:00Z',
  job_id: null,
  supervised: true,
  archived: false,
  counts: { items: 3, ok: 1, failed: 0, skipped: 0 },
} as const

function show(run: Partial<TaskRunSummary>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <RunRow pid={DEMO_PID} run={{ ...base, ...run } as TaskRunSummary} />
    </QueryClientProvider>,
  )
}

test('cleanup pending is shown until the supervisor confirms it; cancel stays available', async () => {
  const cancel = vi.spyOn(api, 'cancelTaskRun').mockResolvedValue({} as never)
  show({ status: 'cleanup_pending', control: { control: 1, id: 'C1', action: 'pause', job_id: 'J', requested_at: 'now', deadline_mono: 0, acknowledged_at: null } })
  expect(await screen.findByText('Cleanup pending')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(/GPUs stay reserved/)
  expect(screen.queryByRole('button', { name: 'Archive' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Resume' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(cancel).toHaveBeenCalledWith(DEMO_PID, base.run_id))
})

test('a running supervised run pauses; a paused one resumes or archives; view-only shows none', async () => {
  const pause = vi.spyOn(api, 'pauseTaskRun').mockResolvedValue({} as never)
  const archive = vi.spyOn(api, 'archiveTaskRun').mockResolvedValue({} as never)
  const { unmount } = show({ status: 'running' })
  fireEvent.click(await screen.findByRole('button', { name: 'Pause' }))
  await waitFor(() => expect(pause).toHaveBeenCalledWith(DEMO_PID, base.run_id))
  unmount()
  const paused = show({ status: 'paused' })
  expect(await screen.findByText('Paused')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Resume' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
  await waitFor(() => expect(archive).toHaveBeenCalledWith(DEMO_PID, base.run_id))
  paused.unmount()
  registry.setReadOnly(true)
  show({ status: 'running' })
  expect(await screen.findByText('Running')).toBeInTheDocument()
  expect(screen.queryByRole('button')).toBeNull()
})

test('D29 phase controls use the displayed attempt and preserve the ordinary task controls', async () => {
  const resume = vi.spyOn(api, 'resumeTaskRun').mockResolvedValue({} as never)
  show({ status: 'interrupted', supervised: false, task: { ...base.task, id: 'analyzer.phase' }, attempts: 3, execution: { phase_step: true, cleanup_verified: true } })
  fireEvent.click(await screen.findByRole('button', { name: 'Resume' }))
  await waitFor(() => expect(resume).toHaveBeenCalledWith(DEMO_PID, base.run_id, { expected_attempt: 3 }))
})
