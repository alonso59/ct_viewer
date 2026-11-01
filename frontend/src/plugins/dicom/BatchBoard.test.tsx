// @vitest-environment jsdom
// UI-25 / DCM-23 / DCM-24: the batch board on hand-written plans (the recording has no batch endpoints).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, test, vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { api, ProblemError, type SourceBatch, type SourceBatchPlan, type SourceOperation } from '../../api'
import { BatchBoard } from './BatchBoard'

const batch = (index: number, patch: Partial<SourceBatch> = {}): SourceBatch => ({
  index, name: `ds-b0${index + 1}`, folder_count: 40, files_total: 1200, operation_id: null, status: 'pending', dataset: null, approved: false, error: null, patients: null, ...patch,
})
const plan = (patch: Partial<SourceBatchPlan> = {}): SourceBatchPlan => ({
  plan_id: 'plan1', source: '/data/source', name: 'ds', batch_size: 40, auto: false, status: 'pending', cursor: 0, counting: 'done', revision: 1,
  created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', warnings: [], batches: [batch(0), batch(1)], ...patch,
})

async function operation(patch: Partial<SourceOperation>): Promise<SourceOperation> {
  const [first] = await api.listSourceOperations()
  if (!first) throw new Error('Missing recorded source operation')
  return { ...(await api.getSourceOperation(first.operation_id)), project_id: null, conversion_run: null, conversion_run_id: null, phase_run: null, ...patch }
}

function renderBoard(value: SourceBatchPlan, props: { onNew?: () => void; onProjectClosed?: () => void } = {}) {
  vi.spyOn(api, 'getSourceBatchPlan').mockResolvedValue(value)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><BatchBoard planId={value.plan_id} onNew={props.onNew ?? (() => undefined)} onProjectClosed={props.onProjectClosed ?? (() => undefined)} /></MemoryRouter></QueryClientProvider>)
}

afterEach(() => vi.restoreAllMocks())

describe('rows and chips', () => {
  test('shows one row per batch with patients, files and a status chip', async () => {
    renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'completed', dataset: '/derived/_datasets/ds-b01' }), batch(1, { status: 'ready', files_total: null })], counting: 'counting' }))
    const first = await screen.findByTestId('batch-0')
    expect(within(first).getByText('Done')).toBeVisible()
    expect(within(first).getByText('1200')).toBeVisible()
    const second = screen.getByTestId('batch-1')
    expect(within(second).getByText('Ready')).toBeVisible()
    expect(within(second).getByText('Counting files…')).toBeVisible()
    expect(screen.getByText('1 of 2 batches converted')).toBeVisible()
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
    fireEvent.click(await screen.findByRole('button', { name: 'Convert this batch' }))
    await waitFor(() => expect(run).toHaveBeenCalledWith('plan1', 'continue'))
    unmount()
    vi.spyOn(api, 'getSourceOperation').mockResolvedValue(await operation({ status: 'running', progress_stage: 'counting', progress: {} }))
    renderBoard(plan({ status: 'running', batches: [batch(0, { status: 'discovering', operation_id: 'op1' }), batch(1)] }))
    await screen.findByTestId('batch-0')
    expect(screen.queryByRole('button', { name: 'Convert this batch' })).toBeNull()
    expect(await screen.findByText('Counting files…')).toBeVisible()
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
    fireEvent.click(await screen.findByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(run).toHaveBeenCalledWith('plan1', 'continue'))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(run).toHaveBeenLastCalledWith('plan1', 'cancel'))
  })

  test('a finished plan has no run controls and offers a new conversion', async () => {
    const onNew = vi.fn()
    renderBoard(plan({ status: 'completed', cursor: 2, batches: [batch(0, { status: 'completed' }), batch(1, { status: 'completed' })] }), { onNew })
    await screen.findByTestId('batch-1')
    for (const name of ['Start', 'Continue', 'Cancel', 'Convert remaining automatically']) expect(screen.queryByRole('button', { name })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'New conversion' }))
    expect(onNew).toHaveBeenCalled()
  })

  test('says so when there are no new folders and shows other refusals as problems', async () => {
    const run = vi.spyOn(api, 'controlSourceBatchPlan').mockRejectedValueOnce(new ProblemError(409, 'conflict', 'Conflict'))
    renderBoard(plan({ status: 'completed', cursor: 2, batches: [batch(0, { status: 'completed' })] }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add new folders' }))
    expect(await screen.findByText('No new folders found.')).toBeVisible()
    run.mockRejectedValueOnce(new ProblemError(422, 'validation', 'Invalid', 'The source changed.'))
    fireEvent.click(screen.getByRole('button', { name: 'Add new folders' }))
    expect(await screen.findByText('The source changed.')).toBeVisible()
    expect(screen.queryByText('No new folders found.')).toBeNull()
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
    const button = await screen.findByRole('button', { name: 'Resume pending work' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)
    await waitFor(() => expect(resume).toHaveBeenCalledWith('op1', { expected_revision: 7, expected_attempt: 2 }))
    expect(screen.getByRole('button', { name: 'Continue' })).toBeVisible()
  })

  test('offers Retry failed series only when series failed and cleanup is verified', async () => {
    const base = await operation({ operation_id: 'op1', status: 'completed_with_errors', cleanup_verified: true })
    const [first] = await api.listSourceOperations()
    const full = await api.getSourceOperation(first!.operation_id)
    if (!full.conversion_run) throw new Error('Missing recorded conversion run')
    const failed: SourceOperation = { ...base, conversion_run: { ...full.conversion_run, counts: { items: 2, ok: 1, failed: 1, pending: 0, skipped: 0 } } }
    vi.spyOn(api, 'getSourceOperation').mockResolvedValue(failed)
    const retry = vi.spyOn(api, 'retryFailedSourceOperation').mockResolvedValue(failed)
    renderBoard(plan({ status: 'paused', batches: [batch(0, { status: 'attention', operation_id: 'op1', error: 'One series failed.' })] }))
    const button = await screen.findByRole('button', { name: 'Retry failed series' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)
    await waitFor(() => expect(retry).toHaveBeenCalledWith('op1', expect.objectContaining({ expected_revision: failed.revision })))
  })
})
