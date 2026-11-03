// @vitest-environment jsdom
// UI-25 / DCM-23 / DCM-24 / DCM-25: the batch board on hand-written plans (the recording has no batch endpoints).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, test, vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { api, ProblemError, type SourceBatch, type SourceBatchPlan, type SourceOperation } from '../../api'
import { BatchBoard, BatchPlanList } from './BatchBoard'

const batch = (index: number, patch: Partial<SourceBatch> = {}): SourceBatch => ({
  index, name: `ds-b0${index + 1}`, folder_count: 40, files_total: 1200, operation_id: null, status: 'pending', dataset: null, approved: false, error: null, patients: null, ...patch,
})
const plan = (patch: Partial<SourceBatchPlan> = {}): SourceBatchPlan => ({
  plan_id: 'plan1', source: '/data/source', name: 'ds', batch_size: 40, auto: false, status: 'pending', cursor: 0, counting: 'done', revision: 1,
  created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', warnings: [], eta: { low_s: null, high_s: null, basis: 'unknown' }, batches: [batch(0), batch(1)], ...patch,
})

async function operation(patch: Partial<SourceOperation>): Promise<SourceOperation> {
  const [first] = await api.listSourceOperations()
  if (!first) throw new Error('Missing recorded source operation')
  return { ...(await api.getSourceOperation(first.operation_id)), project_id: null, conversion_run: null, conversion_run_id: null, phase_run: null, ...patch }
}

function renderBoard(value: SourceBatchPlan, props: { onNew?: () => void; onProjectClosed?: () => void; onOpenOperation?: (id: string) => void } = {}) {
  vi.spyOn(api, 'getSourceBatchPlan').mockResolvedValue(value)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><BatchBoard planId={value.plan_id} onNew={props.onNew ?? (() => undefined)} onProjectClosed={props.onProjectClosed ?? (() => undefined)} onOpenOperation={props.onOpenOperation ?? (() => undefined)} /></MemoryRouter></QueryClientProvider>)
}

afterEach(() => vi.restoreAllMocks())

describe('rows and chips', () => {
  test('shows one row per batch with patients, files and a status chip', async () => {
    renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'completed', dataset: '/derived/_datasets/ds-b01' }), batch(1, { status: 'ready', files_total: null })], counting: 'counting' }))
    const first = await screen.findByTestId('batch-0')
    expect(within(first).getByText('Completed')).toBeVisible()
    expect(within(first).getByText('1200')).toBeVisible()
    const second = screen.getByTestId('batch-1')
    expect(within(second).getByText('Ready')).toBeVisible()
    expect(within(second).getByText('Counting files…')).toBeVisible()
    expect(screen.getByText('1 of 2 batches converted')).toBeVisible()
  })

  test('names the analysis and the source check by the operation, with the analysis counts', async () => {
    const analysis = await operation({ operation_id: 'op1', status: 'running', stage: 'planning', work_kind: 'estimate', progress_stage: 'reading', progress: { files: 1200, files_total: 1200, done: 300, total: 1180 } })
    const check = await operation({ operation_id: 'op2', status: 'running', stage: 'discovering', work_kind: 'convert', conversion_run_id: 'run2', progress: { files: 600, files_total: 1200 } })
    vi.spyOn(api, 'getSourceOperation').mockImplementation(async (id) => (id === 'op1' ? analysis : check))
    renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'discovering', operation_id: 'op1' }), batch(1, { status: 'converting', operation_id: 'op2' })] }))
    const first = await screen.findByTestId('batch-0')
    expect(await within(first).findByText('Analysis')).toBeVisible()
    expect(within(first).getByText('Reading headers · 300 / 1,180')).toBeVisible()
    const second = screen.getByTestId('batch-1')
    expect(await within(second).findByText('Checking source')).toBeVisible()
    expect(within(second).getByText('Checking the source · 600 / 1,200')).toBeVisible()
  })

  test('lists every plan that is not cancelled so its board can be reopened', async () => {
    vi.spyOn(api, 'listSourceBatchPlans').mockResolvedValue([
      plan({ plan_id: 'p1', name: 'first', status: 'paused', batches: [batch(0, { status: 'completed' }), batch(1)] }),
      plan({ plan_id: 'p2', name: 'gone', status: 'cancelled' }),
    ])
    const onOpen = vi.fn()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><BatchPlanList current={null} onOpen={onOpen} /></QueryClientProvider>)
    const list = await screen.findByTestId('batch-plans')
    expect(within(list).getByText('Batch plans (1)')).toBeInTheDocument()
    expect(within(list).getByText('1 of 2 batches converted')).toBeInTheDocument()
    expect(within(list).queryByText('gone')).toBeNull()
    fireEvent.click(within(list).getByRole('button', { name: 'Open' }))
    expect(onOpen).toHaveBeenCalledWith('p1')
  })

  test('a batch with an operation opens its conversion details', async () => {
    vi.spyOn(api, 'getSourceOperation').mockResolvedValue(await operation({ operation_id: 'op1', status: 'completed' }))
    const onOpenOperation = vi.fn()
    renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'converting', operation_id: 'op1' }), batch(1)] }), { onOpenOperation })
    fireEvent.click(within(await screen.findByTestId('batch-0')).getByRole('button', { name: 'Details' }))
    expect(onOpenOperation).toHaveBeenCalledWith('op1')
    expect(within(screen.getByTestId('batch-1')).queryByRole('button', { name: 'Details' })).toBeNull()
  })

  test('a batch whose operation was resumed shows it converting, not its old error', async () => {
    const recorded = await operation({ operation_id: 'op1' })
    vi.spyOn(api, 'getSourceOperation').mockResolvedValue({ ...recorded, status: 'running', stage: 'converting', conversion_run: recorded.conversion_run ?? null })
    renderBoard(plan({ status: 'paused', batches: [batch(0, { status: 'attention', operation_id: 'op1', error: 'Out of memory' }), batch(1)] }))
    const row = await screen.findByTestId('batch-0')
    expect(await within(row).findByText('Converting')).toBeVisible()
    expect(within(row).queryByText('Out of memory')).toBeNull()
  })

  test('problems are listed under the table with the last line of the report first', async () => {
    vi.spyOn(api, 'getSourceOperation').mockResolvedValue(await operation({ operation_id: 'op1', status: 'failed' }))
    const report = ['RuntimeError: input_manifest(g.series)', '  File "commits.py", line 55', 'OSError: [Errno 12] Cannot allocate memory'].join('\n')
    renderBoard(plan({ status: 'paused', batches: [batch(0, { status: 'attention', operation_id: 'op1', error: report }), batch(1)] }))
    const problems = await screen.findByRole('list', { name: 'Batch problems' })
    expect(within(problems).getByRole('alert')).toHaveTextContent('ds-b01 · OSError: [Errno 12] Cannot allocate memory')
    expect(within(screen.getByTestId('batch-0')).queryByText(/Cannot allocate memory/)).toBeNull()
    expect(within(problems).getByText('Details')).toBeInTheDocument()
  })

  test('shows a dash for files when counting is over without a count', async () => {
    renderBoard(plan({ batches: [batch(0, { files_total: null }), batch(1)] }))
    expect(within(await screen.findByTestId('batch-0')).getByText('—')).toBeVisible()
  })
})

describe('plan controls', () => {
  test('a new plan starts at batch 1', async () => {
    const start = vi.spyOn(api, 'controlSourceBatchPlan').mockResolvedValue(plan({ status: 'running' }))
    renderBoard(plan())
    fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
    await waitFor(() => expect(start).toHaveBeenCalledWith('plan1', 'start'))
    expect(screen.queryByRole('button', { name: 'Convert this batch' })).toBeNull()
  })

  test('a ready batch converts on request and a discovering one does not offer it', async () => {
    const run = vi.spyOn(api, 'controlSourceBatchPlan').mockResolvedValue(plan({ status: 'running' }))
    const { unmount } = renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'ready' }), batch(1)] }))
    // UI-28: a running plan that waits for this click says so instead of just "Running"
    expect(await screen.findByText('Ready: convert this batch')).toBeVisible()
    fireEvent.click(await screen.findByRole('button', { name: 'Convert this batch' }))
    await waitFor(() => expect(run).toHaveBeenCalledWith('plan1', 'continue'))
    unmount()
    vi.spyOn(api, 'getSourceOperation').mockResolvedValue(await operation({ status: 'running', progress_stage: 'counting', progress: {} }))
    renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'discovering', operation_id: 'op1' }), batch(1)] }))
    await screen.findByTestId('batch-0')
    expect(screen.queryByRole('button', { name: 'Convert this batch' })).toBeNull()
    expect(await screen.findByText('Counting files')).toBeVisible()
  })

  test('toggles automatic conversion of the remaining batches', async () => {
    const auto = vi.spyOn(api, 'setSourceBatchAuto').mockResolvedValue(plan({ status: 'running', auto: true }))
    renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'converting' }), batch(1)] }))
    fireEvent.click(await screen.findByRole('button', { name: 'Convert remaining automatically' }))
    await waitFor(() => expect(auto).toHaveBeenCalledWith('plan1', true))
    expect(await screen.findByRole('button', { name: 'Stop automatic conversion' })).toBeVisible()
  })

  test('a paused plan continues and can be cancelled', async () => {
    const run = vi.spyOn(api, 'controlSourceBatchPlan').mockResolvedValue(plan({ status: 'running' }))
    renderBoard(plan({ status: 'paused', batches: [batch(0, { status: 'attention', error: 'Conversion stopped.' }), batch(1)] }))
    fireEvent.click(await screen.findByRole('button', { name: 'Resume plan' }))
    await waitFor(() => expect(run).toHaveBeenCalledWith('plan1', 'continue'))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel plan' }))
    expect(run).not.toHaveBeenLastCalledWith('plan1', 'cancel')
    fireEvent.click(screen.getByRole('button', { name: 'Yes, cancel' }))
    await waitFor(() => expect(run).toHaveBeenLastCalledWith('plan1', 'cancel'))
  })

  test('a finished plan has no run controls and offers a new conversion', async () => {
    const onNew = vi.fn()
    renderBoard(plan({ status: 'completed', cursor: 2, batches: [batch(0, { status: 'completed' }), batch(1, { status: 'completed' })] }), { onNew })
    await screen.findByTestId('batch-1')
    for (const name of ['Start', 'Resume plan', 'Cancel plan', 'Add new folders', 'Convert remaining automatically']) expect(screen.queryByRole('button', { name })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'New conversion' }))
    expect(onNew).toHaveBeenCalled()
  })

  test('says so when there are no new folders and shows other refusals as problems', async () => {
    const run = vi.spyOn(api, 'controlSourceBatchPlan').mockRejectedValueOnce(new ProblemError(409, 'conflict', 'Conflict'))
    renderBoard(plan({ status: 'paused', batches: [batch(0, { status: 'completed' }), batch(1)] }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add new folders' }))
    expect(await screen.findByText('No new folders found.')).toBeVisible()
    run.mockRejectedValueOnce(new ProblemError(422, 'validation', 'Invalid', 'The source changed.'))
    fireEvent.click(screen.getByRole('button', { name: 'Add new folders' }))
    expect(await screen.findByText('The source changed.')).toBeVisible()
    expect(screen.queryByText('No new folders found.')).toBeNull()
  })
})

describe('time left', () => {
  test('shows the remaining time of all batches once completed batches measured it', async () => {
    renderBoard(plan({ status: 'running', eta: { low_s: 4 * 3600, high_s: 6 * 3600, basis: 'completed_batches' }, batches: [batch(0, { status: 'completed' }), batch(1, { status: 'ready' })] }))
    expect(await screen.findByTestId('batch-overall-eta')).toHaveTextContent('All batches: about 4–6 h left')
  })

  test('shows nothing before a batch has completed or after the plan ends', async () => {
    const { unmount } = renderBoard(plan({ status: 'running' }))
    await screen.findByTestId('batch-0')
    expect(screen.queryByTestId('batch-overall-eta')).toBeNull()
    unmount()
    renderBoard(plan({ status: 'completed', cursor: 2, eta: { low_s: 60, high_s: 120, basis: 'completed_batches' } }))
    await screen.findByTestId('batch-0')
    expect(screen.queryByTestId('batch-overall-eta')).toBeNull()
  })

  test('shows converted bytes and speed while the series time estimate is unknown', async () => {
    const base = await operation({ operation_id: 'op1', status: 'running' })
    const [first] = await api.listSourceOperations()
    const full = await api.getSourceOperation(first!.operation_id)
    if (!full.conversion_run) throw new Error('Missing recorded conversion run')
    const running: SourceOperation = { ...base, conversion_run: { ...full.conversion_run, conversion_time: { basis: 'unknown', confidence: 'unknown', sample_count: 0, remaining_units: 3, estimated_s: null, lower_s: null, upper_s: null }, progress: { done: 1, total: 4, stage_done: 1, stage_total: 4, bytes_done: 250_000_000, bytes_total: 1_000_000_000, bytes_per_s: 5_000_000 } } }
    vi.spyOn(api, 'getSourceOperation').mockResolvedValue(running)
    renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'converting', operation_id: 'op1' })] }))
    expect(await screen.findByText('250 MB of 1 GB converted · 25%')).toBeVisible()
    expect(screen.getByText('Speed: 5 MB per second')).toBeVisible()
  })
})

describe('warnings', () => {
  test('lists patients that are already in an earlier batch without any identifier', async () => {
    renderBoard(plan({ warnings: [{ code: 'patient_in_earlier_batch', batch_index: 1, earlier_batches: [0], patients: 3, message: 'internal' }] }))
    const note = await screen.findByRole('note')
    expect(note).toHaveTextContent('ds-b02 has 3 patients that are already in an earlier batch.')
    expect(screen.queryByText('internal')).toBeNull()
  })
})

describe('completed batches', () => {
  test('Create project is manual and opens the dialog with the dataset and the batch name', async () => {
    const onProjectClosed = vi.fn()
    renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'completed', dataset: '/derived/_datasets/ds-b01' }), batch(1, { status: 'ready' })] }), { onProjectClosed })
    const row = await screen.findByTestId('batch-0')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(within(screen.getByTestId('batch-1')).queryByRole('button', { name: 'Create project' })).toBeNull()
    fireEvent.click(within(row).getByRole('button', { name: 'Create project' }))
    const dialog = await screen.findByRole('dialog', { name: 'New project' })
    expect(within(dialog).getByLabelText('Project name')).toHaveValue('ds-b01')
    expect(within(dialog).getByDisplayValue('/derived/_datasets/ds-b01')).toBeVisible()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(onProjectClosed).toHaveBeenCalled())
  })
})

describe('batches that need attention', () => {
  test('shows the error and resumes or retries the batch operation before the plan continues', async () => {
    const stopped = await operation({ operation_id: 'op1', status: 'failed', cleanup_verified: true, revision: 7, attempt: 2 })
    vi.spyOn(api, 'getSourceOperation').mockResolvedValue({ ...stopped, conversion_run: null })
    const resume = vi.spyOn(api, 'resumeSourceOperation').mockResolvedValue({ ...stopped, status: 'running' })
    renderBoard(plan({ status: 'paused', batches: [batch(0, { status: 'attention', operation_id: 'op1', error: 'Conversion stopped.' }), batch(1)] }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Conversion stopped.')
    const button = await screen.findByRole('button', { name: 'Resume' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)
    await waitFor(() => expect(resume).toHaveBeenCalledWith('op1', { expected_revision: 7, expected_attempt: 2 }))
    expect(screen.getByRole('button', { name: 'Resume plan' })).toBeVisible()
  })

  test('offers Retry failed only when series failed and cleanup is verified', async () => {
    const base = await operation({ operation_id: 'op1', status: 'completed_with_errors', cleanup_verified: true })
    const [first] = await api.listSourceOperations()
    const full = await api.getSourceOperation(first!.operation_id)
    if (!full.conversion_run) throw new Error('Missing recorded conversion run')
    const failed: SourceOperation = { ...base, conversion_run: { ...full.conversion_run, counts: { items: 2, ok: 1, failed: 1, pending: 0, skipped: 0 } } }
    vi.spyOn(api, 'getSourceOperation').mockResolvedValue(failed)
    const retry = vi.spyOn(api, 'retryFailedSourceOperation').mockResolvedValue(failed)
    renderBoard(plan({ status: 'paused', batches: [batch(0, { status: 'attention', operation_id: 'op1', error: 'One series failed.' })] }))
    const button = await screen.findByRole('button', { name: 'Retry failed' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)
    await waitFor(() => expect(retry).toHaveBeenCalledWith('op1', expect.objectContaining({ expected_revision: failed.revision })))
  })
})
