// @vitest-environment jsdom
// UI-25 on the recorded API (TST-04): source → settings → dry run → run → result with the three
// next steps. The recording converted `dicom/P900` of the fixtures (one series, one scout).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { api, ProblemError, type SourceOperation } from '../../api'
import { fmtBytes } from '../../lib'
import ConverterOverlay from './ConverterOverlay'
import { defaultDatasetName, useConverter } from './store'

async function recordedOperation(): Promise<SourceOperation> {
  const [operation] = await api.listSourceOperations()
  if (!operation) throw new Error('Missing recorded source operation')
  return api.getSourceOperation(operation.operation_id)
}

afterEach(() => { useConverter.getState().close(); vi.restoreAllMocks() })

test.each([false, true])('D29 retries and cancels only the separate phase run (project: %s)', async (inProject) => {
  const recorded = await recordedOperation()
  if (!recorded.conversion_run) throw new Error('Missing recorded conversion run')
  const phaseId = '01ARZ3NDEKTSV4RRFFQ69G5FAV'
  const phase = { ...recorded.conversion_run, run_id: phaseId, task: { id: 'analyzer.phase', version: '1.0.0', manifest_hash: 'phase' }, status: 'failed' as const, attempts: 2, cleanup_verified: true, execution: { phase_step: true, cleanup_verified: true }, progress: { done: 0, total: 1, stage_done: 0, stage_total: 1 }, counts: { items: 1, ok: 0, failed: 1, skipped: 0, pending: 0 }, error: 'Phase batch failed' }
  const operation: SourceOperation = { ...recorded, project_id: inProject ? 'project-phase' : null, phase_run: phase }
  const get = vi.spyOn(api, 'getSourceOperation').mockResolvedValue(operation)
  const start = { run_id: phaseId, job_id: 'phase-attempt-3', status: 'queued' as const }
  const resume = vi.spyOn(api, inProject ? 'resumeTaskRun' : 'resumeWorkspaceRun').mockImplementation(async () => {
    get.mockResolvedValue({ ...operation, phase_run: { ...phase, status: 'running', attempts: 3, error: null } })
    return start
  })
  const cancel = vi.spyOn(api, inProject ? 'cancelTaskRun' : 'cancelWorkspaceRun').mockResolvedValue(phase as never)
  const conversion = vi.spyOn(api, 'resumeSourceOperation')
  useConverter.getState().attach(operation.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: 'Retry phase analysis' }))
  await waitFor(() => expect(resume).toHaveBeenCalledWith(...(inProject ? ['project-phase', phaseId, { expected_attempt: 2 }] : [phaseId, { expected_attempt: 2 }])))
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel phase analysis' }))
  await waitFor(() => expect(cancel).toHaveBeenCalledWith(...(inProject ? ['project-phase', phaseId, { expected_attempt: 3 }] : [phaseId, { expected_attempt: 3 }])))
  expect(conversion).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Show the result' })).toBeEnabled()
})

test('D29 keeps polling phase after conversion completes and minimizes while phase is active', async () => {
  const recorded = await recordedOperation()
  if (!recorded.phase_run) throw new Error('Missing recorded phase run')
  const pending: SourceOperation = { ...recorded, phase_run: { ...recorded.phase_run, status: 'running', progress: { done: 1, total: 2, stage_done: 1, stage_total: 2 } } }
  const get = vi.spyOn(api, 'getSourceOperation').mockResolvedValue(pending)
  useConverter.getState().attach(recorded.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('1 of 2 metadata rows analyzed')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Minimize' }))
  expect(screen.getByTestId('conv-chip')).toHaveTextContent('Phase analysis')
  get.mockResolvedValue({ ...recorded, phase_run: { ...recorded.phase_run, status: 'completed' } })
  await waitFor(() => expect(screen.getByTestId('conv-chip')).toHaveTextContent('Completed'), { timeout: 3000 })
  fireEvent.click(screen.getByRole('button', { name: 'Show' }))
  const panel = screen.getByRole('region', { name: 'Phase analysis' })
  expect(within(panel).getByText('Completed')).toBeInTheDocument()
  expect(within(panel).queryByRole('button', { name: 'Cancel phase analysis' })).toBeNull()
})

test('D29 never enables phase retry with unverified cleanup', async () => {
  const recorded = await recordedOperation()
  if (!recorded.phase_run) throw new Error('Missing recorded phase run')
  vi.spyOn(api, 'getSourceOperation').mockResolvedValue({ ...recorded, phase_run: { ...recorded.phase_run, status: 'interrupted', cleanup_verified: false, execution: { phase_step: true, cleanup_verified: false } } })
  useConverter.getState().attach(recorded.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('button', { name: 'Retry phase analysis' })).toBeDisabled()
})

test('D29 requires completed conversion before retrying phase', async () => {
  const recorded = await recordedOperation()
  if (!recorded.phase_run || !recorded.conversion_run) throw new Error('Missing recorded runs')
  vi.spyOn(api, 'getSourceOperation').mockResolvedValue({ ...recorded, status: 'interrupted', conversion_run: { ...recorded.conversion_run, status: 'interrupted' }, phase_run: { ...recorded.phase_run, status: 'interrupted', cleanup_verified: true, execution: { phase_step: true, cleanup_verified: true } } })
  useConverter.getState().attach(recorded.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('button', { name: 'Retry phase analysis' })).toBeDisabled()
})

test('UI-28 restores a conversion from the server using its stored opaque ID', async () => {
  const operation = await recordedOperation()
  const get = vi.spyOn(api, 'getSourceOperation').mockResolvedValue(operation)
  useConverter.getState().close()
  useConverter.getState().attach(operation.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('button', { name: 'Show the result' })).toBeInTheDocument()
  expect(get).toHaveBeenCalledWith(operation.operation_id)
  expect(useConverter.getState().source).toBe(operation.source)
  expect(useConverter.getState().run?.rid).toBe(operation.conversion_run_id)
  useConverter.getState().close()
  vi.restoreAllMocks()
})

test.each([false, true])('UI-28 resumes the same interrupted server operation (pending receipt: %s)', async (pending) => {
  const completed = await recordedOperation()
  if (!completed.conversion_run) throw new Error('Missing recorded conversion run')
  const command = { expected_revision: completed.revision, expected_attempt: completed.attempt, expected_run_attempt: completed.conversion_run.attempts }
  const interrupted: SourceOperation = { ...completed, revision: pending ? completed.revision + 1 : completed.revision, status: 'interrupted', cleanup_verified: true, conversion_run: { ...completed.conversion_run, status: 'interrupted' }, pending_control: pending ? { action: 'resume', request: command, run_attempt: completed.conversion_run.attempts, request_id: 'opaque-receipt' } : null }
  const running: SourceOperation = { ...completed, status: 'running', cleanup_verified: false, revision: completed.revision + 1, attempt: completed.attempt + 1, conversion_run: { ...completed.conversion_run, status: 'running', attempts: 2 } }
  const get = vi.spyOn(api, 'getSourceOperation').mockResolvedValue(interrupted)
  const resume = vi.spyOn(api, 'resumeSourceOperation').mockImplementation(async () => { get.mockResolvedValue(running); return running })
  useConverter.getState().attach(interrupted.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: 'Resume pending work' }))
  await waitFor(() => expect(resume).toHaveBeenCalledWith(interrupted.operation_id, command))
  expect(await screen.findByRole('button', { name: 'Cancel conversion' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Show the result' })).toBeNull()
  expect(useConverter.getState().run?.rid).toBe(completed.conversion_run_id)
})

test.each([false, true])('D23 retries only recorded failures and shows pending work (pending receipt: %s)', async (pending) => {
  const completed = await recordedOperation()
  if (!completed.conversion_run) throw new Error('Missing recorded conversion run')
  const command = { expected_revision: completed.revision, expected_attempt: completed.attempt, expected_run_attempt: completed.conversion_run.attempts }
  const interrupted: SourceOperation = { ...completed, status: 'interrupted', cleanup_verified: true, conversion_run: { ...completed.conversion_run, status: 'interrupted', counts: { items: 3, ok: 1, failed: 1, pending: 1, skipped: 0, converted: 1 } }, pending_control: pending ? { action: 'retry_failed', request: command, run_attempt: completed.conversion_run.attempts, request_id: 'retry-receipt' } : null }
  const get = vi.spyOn(api, 'getSourceOperation').mockResolvedValue(interrupted)
  const retry = vi.spyOn(api, 'retryFailedSourceOperation').mockImplementation(async () => {
    const running = { ...interrupted, status: 'running' as const, pending_control: null, cleanup_verified: false }
    get.mockResolvedValue(running)
    return running
  })
  const resume = vi.spyOn(api, 'resumeSourceOperation')
  useConverter.getState().attach(interrupted.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('1 verified complete · 1 failed · 1 pending')).toBeInTheDocument()
  if (pending) expect(screen.getByRole('button', { name: 'Resume pending work' })).toBeDisabled()
  else expect(screen.getByRole('button', { name: 'Resume pending work' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry failed series' }))
  await waitFor(() => expect(retry).toHaveBeenCalledWith(interrupted.operation_id, command))
  expect(resume).not.toHaveBeenCalled()
})

test.each([false, true])('D23 blocks retry when cleanup is unknown or no failures remain (%s)', async (noFailures) => {
  const completed = await recordedOperation()
  if (!completed.conversion_run) throw new Error('Missing recorded conversion run')
  const interrupted: SourceOperation = { ...completed, status: 'interrupted', cleanup_verified: noFailures, conversion_run: { ...completed.conversion_run, status: 'interrupted', counts: { items: 2, ok: 1, failed: noFailures ? 0 : 1, pending: noFailures ? 1 : 0, skipped: 0 } } }
  vi.spyOn(api, 'getSourceOperation').mockResolvedValue(interrupted)
  useConverter.getState().attach(interrupted.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  await screen.findByRole('button', { name: 'Resume pending work' })
  if (noFailures) expect(screen.queryByRole('button', { name: 'Retry failed series' })).toBeNull()
  else expect(screen.getByRole('button', { name: 'Retry failed series' })).toBeDisabled()
})

test('UI-28 reads bounded plan pages and forwards filter/cursor controls', async () => {
  const completed = await recordedOperation()
  const ready: SourceOperation = { ...completed, status: 'completed', stage: 'ready', work_kind: 'estimate', conversion_run: null, conversion_run_id: null }
  const page = await api.sourceOperationPlan(ready.operation_id)
  vi.spyOn(api, 'getSourceOperation').mockResolvedValue(ready)
  const plan = vi.spyOn(api, 'sourceOperationPlan').mockImplementation(async (_id, options) => ({ ...page, total: page.items.length * 2, next_cursor: options?.cursor ? null : 'next-opaque-page', items: options?.cursor ? page.items.map((row) => ({ ...row, case_id: `other-${row.case_id}` })) : page.items }))
  useConverter.getState().attach(ready.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  const next = await screen.findByRole('button', { name: 'Next page' })
  await waitFor(() => expect(next).toBeEnabled())
  fireEvent.click(next)
  await waitFor(() => expect(plan).toHaveBeenCalledWith(ready.operation_id, { cursor: 'next-opaque-page', action: undefined }))
  fireEvent.change(screen.getByRole('combobox', { name: 'Show series' }), { target: { value: 'skip' } })
  await waitFor(() => expect(plan).toHaveBeenLastCalledWith(ready.operation_id, { cursor: undefined, action: 'skip' }))
})

test('DCM-15 re-estimates changed options in the same operation and inventory', async () => {
  const completed = await recordedOperation()
  const ready: SourceOperation = { ...completed, status: 'completed', stage: 'ready', work_kind: 'estimate', conversion_run: null, conversion_run_id: null, dataset_name: 'original-output' }
  const get = vi.spyOn(api, 'getSourceOperation').mockResolvedValue(ready)
  const start = vi.spyOn(api, 'startSourceOperation')
  const refresh = vi.spyOn(api, 'estimateSourceOperation').mockImplementation(async () => {
    const updated: SourceOperation = { ...ready, revision: ready.revision + 1, attempt: ready.attempt + 1, plan_attempt: (ready.plan_attempt ?? 0) + 1, dataset_name: 'revised-output', settings: { ...ready.settings, phase_analyzer: false, anonymize: 'basic' } }
    get.mockResolvedValue(updated)
    return updated
  })
  useConverter.getState().attach(ready.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: 'Back' }))
  expect(useConverter.getState().operationId).toBe(ready.operation_id)
  fireEvent.change(screen.getByRole('textbox', { name: 'Dataset name' }), { target: { value: 'revised-output' } })
  fireEvent.click(screen.getByRole('checkbox', { name: /phase analyzer/ }))
  fireEvent.click(screen.getByRole('checkbox', { name: /Anonymize/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Dry run' }))
  await waitFor(() => expect(refresh).toHaveBeenCalledWith(ready.operation_id, { expected_revision: ready.revision, expected_attempt: ready.attempt, settings: { target_profile: 'generic', phase_analyzer: false, anonymize: 'basic' }, name: 'revised-output' }))
  expect(start).not.toHaveBeenCalled()
  expect(await screen.findByRole('button', { name: /Convert \d+ series/ })).toBeEnabled()
  expect(useConverter.getState().settings.name).toBe('revised-output')
})

test('DCM-15 changing the destination starts a workspace operation instead of reusing the project plan', async () => {
  const completed = await recordedOperation()
  const [project] = await api.listProjects()
  if (!project) throw new Error('Missing recorded project')
  const ready: SourceOperation = { ...completed, project_id: project.project_id, status: 'completed', stage: 'ready', work_kind: 'estimate', conversion_run: null, conversion_run_id: null }
  const pending: SourceOperation = { ...ready, operation_id: '01ARZ3NDEKTSV4RRFFQ69G5FAV', project_id: null, status: 'queued', stage: 'discovering', estimate: null, plan_attempt: null }
  vi.spyOn(api, 'getSourceOperation').mockImplementation(async (id) => id === ready.operation_id ? ready : pending)
  const start = vi.spyOn(api, 'startSourceOperation').mockResolvedValue(pending)
  const refresh = vi.spyOn(api, 'estimateSourceOperation').mockResolvedValue(ready)
  useConverter.getState().attach(ready.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: 'Back' }))
  fireEvent.click(screen.getByRole('button', { name: 'As a dataset (no project)' }))
  fireEvent.click(screen.getByRole('button', { name: 'Dry run' }))
  await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({ path: ready.source, project_id: null })))
  expect(refresh).not.toHaveBeenCalled()
})

test('D22 refreshes a stale dry-run fence without replaying the rejected command', async () => {
  const completed = await recordedOperation()
  const ready: SourceOperation = { ...completed, status: 'completed', stage: 'ready', work_kind: 'estimate', conversion_run: null, conversion_run_id: null }
  const latest: SourceOperation = { ...ready, revision: ready.revision + 2, attempt: ready.attempt + 1 }
  const get = vi.spyOn(api, 'getSourceOperation').mockResolvedValue(ready)
  const refresh = vi.spyOn(api, 'estimateSourceOperation').mockImplementationOnce(async () => {
    get.mockResolvedValue(latest)
    throw new ProblemError(409, 'job-conflict', 'The plan changed')
  }).mockResolvedValue(latest)
  useConverter.getState().attach(ready.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: 'Back' }))
  fireEvent.click(screen.getByRole('button', { name: 'Dry run' }))
  await screen.findByRole('alert')
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
  expect(refresh).toHaveBeenCalledTimes(1)
  fireEvent.click(await screen.findByRole('button', { name: 'Back' }))
  fireEvent.click(screen.getByRole('button', { name: 'Dry run' }))
  await waitFor(() => expect(refresh).toHaveBeenLastCalledWith(ready.operation_id, expect.objectContaining({ expected_revision: latest.revision, expected_attempt: latest.attempt })))
})

test('UI-18 preserves background dry-run refusal actions for non-DICOM sources', async () => {
  const completed = await recordedOperation()
  const failed: SourceOperation = { ...completed, source: '/data/nifti', status: 'failed', stage: 'planning', work_kind: 'estimate', estimate: null, conversion_run_id: null, conversion_run: null, error: 'No DICOM files in nifti; 1 NIfTI files found', problem: { status: 415, type: '/problems/unsupported-format', title: 'Unsupported format', detail: 'No DICOM files in nifti; 1 NIfTI files found', actions: ['open', 'import_as:nifti-files', 'choose_another_path'] } }
  vi.spyOn(api, 'getSourceOperation').mockResolvedValue(failed)
  useConverter.getState().attach(failed.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(failed.error!)
  expect(screen.getByRole('button', { name: 'Open without a project' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Create project from this' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Choose another file or folder' }))
  expect(useConverter.getState()).toMatchObject({ operationId: null, requestKey: null, step: 'source' })
})

test.each([900, null])('D27 shows the runner memory requirement and budget (%s MiB)', async (required) => {
  const completed = await recordedOperation()
  if (!completed.conversion_run || !('dataset_dir' in completed.conversion_run)) throw new Error('Missing recorded workspace run')
  const waiting: SourceOperation = { ...completed, status: 'waiting_for_resources', error: null, conversion_run: { ...completed.conversion_run, status: 'waiting_for_resources', resource_wait: { budget_mb: 512, required_mb: required, reason: required === null ? 'unknown_geometry' : 'memory_budget' } } }
  vi.spyOn(api, 'getSourceOperation').mockResolvedValue(waiting)
  useConverter.getState().attach(waiting.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText(required === null ? /geometry does not provide a reliable memory estimate/ : /Estimated memory: 900 MiB.*Current budget: 512 MiB/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Cancel conversion' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: 'Show the result' })).toBeNull()
})

test('DCM-16 distinguishes committed volume progress from phase metadata progress', async () => {
  const completed = await recordedOperation()
  if (!completed.conversion_run || !('dataset_dir' in completed.conversion_run)) throw new Error('Missing recorded workspace run')
  const analyzing: SourceOperation = { ...completed, status: 'running', conversion_run: { ...completed.conversion_run, status: 'running', progress: { done: 1, total: 1, stage: 'analyzing', stage_done: 0, stage_total: 1 } } }
  vi.spyOn(api, 'getSourceOperation').mockResolvedValue(analyzing)
  useConverter.getState().attach(analyzing.operation_id)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('Converted: 1 / 1 selected series · Analyzing phase: 0 / 1 rows')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Cancel conversion' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: 'Show the result' })).toBeNull()
})

test('converts a DICOM folder into a workspace dataset without a project', async () => {
  const completed = await recordedOperation()
  const ready: SourceOperation = { ...completed, stage: 'ready', work_kind: 'estimate', conversion_run_id: null, conversion_run: null }
  const get = vi.spyOn(api, 'getSourceOperation').mockResolvedValue(ready)
  const realConvert = api.convertSourceOperation.bind(api)
  vi.spyOn(api, 'convertSourceOperation').mockImplementation(async (...args) => {
    get.mockResolvedValue(completed)
    return realConvert(...args)
  })
  useConverter.getState().show({ source: '/data/dicom/P900', pid: null })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ConverterOverlay />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  // A prefilled source starts on Settings (Open mode on DICOM)
  expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('Settings')
  // AUD-A5-16 (NFR-17): the suggested name is neutral, never the (patient) folder name
  const name = defaultDatasetName()
  expect(screen.getByDisplayValue(name)).toBeInTheDocument()
  expect(screen.queryByDisplayValue('P900')).toBeNull()
  expect(screen.getByRole('checkbox', { name: /phase analyzer/ })).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'Dry run' }))
  const convert = await screen.findByRole('button', { name: 'Convert 1 series' })
  // DCM-06 (AUD-A2-13): which series is skipped and why; storage in the unit that fits
  expect(screen.getByText('2 series · 1 skipped')).toBeInTheDocument()
  expect(await screen.findByText('Skip: localizer / scout')).toBeInTheDocument()
  expect(screen.getAllByText(fmtBytes(1512)).length).toBeGreaterThan(0)
  fireEvent.click(convert)
  fireEvent.click(await screen.findByRole('button', { name: 'Show the result' }, { timeout: 3000 }))
  // the recorded run: its name and folder are the recording day's
  const [run] = await api.listWorkspaceRuns()
  expect(await screen.findByText(`Dataset ${run!.name} is ready.`)).toBeInTheDocument()
  expect(screen.getByText(run!.dataset_dir!)).toBeInTheDocument()
  for (const name of ['Open', 'Create project from this', 'Add to project']) expect(screen.getByRole('button', { name })).toBeInTheDocument()
})

test('a dataset name that is taken is said in the settings step (DCM-14, AUD-A2-14)', async () => {
  // the recorded workspace run holds a dataset name
  const [run] = await api.listWorkspaceRuns()
  const name = run!.name
  useConverter.getState().show({ source: '/data/dicom/P900', pid: null })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ConverterOverlay />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.change(screen.getByDisplayValue(defaultDatasetName()), { target: { value: name } })
  expect(await screen.findByText(`A dataset named ${name} exists; this one will be saved as ${name}-1.`)).toBeInTheDocument()
  fireEvent.change(screen.getByDisplayValue(name), { target: { value: 'fresh name' } })
  expect(screen.queryByText(/exists; this one will be saved/)).toBeNull()
})

test('a dry run shows its stages, minimizes to a chip while it works and can be cancelled (UI-25, DCM-06)', async () => {
  const completed = await recordedOperation()
  const pending: SourceOperation = { ...completed, status: 'running', stage: 'planning', work_kind: 'estimate', conversion_run_id: null, conversion_run: null, estimate: null, progress_stage: 'reading', progress: { done: 120, total: 450 }, cleanup_verified: false }
  const est = vi.spyOn(api, 'startSourceOperation').mockResolvedValue(pending)
  const prog = vi.spyOn(api, 'getSourceOperation').mockResolvedValue(pending)
  const stopping = { ...pending, status: 'cancelling' as const }
  const cancel = vi.spyOn(api, 'cancelSourceOperation').mockImplementation(async () => { prog.mockResolvedValue(stopping); return stopping })
  useConverter.getState().show({ source: '/data/dicom/P900', pid: null })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ConverterOverlay />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Dry run' }))
  const progressId = est.mock.calls[0]?.[0].idempotency_key
  expect(progressId).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
  expect(await screen.findByText('Reading headers: 120 / 450 files')).toBeInTheDocument()
  expect(prog).toHaveBeenCalledWith(pending.operation_id)
  // × while it works minimizes (nothing is lost); the chip says where it is
  fireEvent.click(screen.getByRole('button', { name: 'close' }))
  expect(useConverter.getState()).toMatchObject({ open: true, minimized: true, working: true })
  const chip = await screen.findByTestId('conv-chip')
  expect(chip).toHaveTextContent('Reading headers: 120 / 450 files')
  // opening the converter again shows the running window instead of starting over
  useConverter.getState().show({ source: '/data/other', pid: null })
  expect(useConverter.getState()).toMatchObject({ minimized: false, source: '/data/dicom/P900' })
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel dry run' }))
  expect(cancel).toHaveBeenCalledWith(pending.operation_id, { expected_revision: pending.revision, expected_attempt: pending.attempt })
  expect(useConverter.getState().working).toBe(true)
  prog.mockResolvedValue({ ...pending, status: 'cancelled', cleanup_verified: true })
  expect(await screen.findByRole('button', { name: 'Dry run' }, { timeout: 3000 })).toBeInTheDocument()
  expect(useConverter.getState().working).toBe(false)
  vi.restoreAllMocks()
})

test.each([
  ['waiting_for_resources', 'Waiting for resources…'],
  ['cancelling', 'Cancelling…'],
  ['cleanup_pending', 'Verifying that execution stopped…'],
] as const)('keeps %s active until the server confirms completion', async (status, label) => {
  const [run] = await api.listWorkspaceRuns()
  const poll = vi.spyOn(api, 'getWorkspaceRun').mockResolvedValue({ ...run!, status })
  useConverter.getState().close()
  useConverter.getState().show({ source: '/data/dicom/P900', pid: null })
  useConverter.getState().patch({ step: 'run', run: { kind: 'dataset', rid: run!.run_id } })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rendered = render(
    <QueryClientProvider client={qc}><MemoryRouter><ConverterOverlay /></MemoryRouter></QueryClientProvider>,
  )
  try {
    expect(await screen.findByText(label)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show the result' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Cancel conversion' })).toBeInTheDocument()
    poll.mockResolvedValue({ ...run!, status: 'cancelled' })
    expect(await screen.findByRole('button', { name: 'Show the result' }, { timeout: 2500 })).toBeInTheDocument()
  } finally {
    rendered.unmount()
    qc.clear()
    useConverter.getState().close()
    vi.restoreAllMocks()
  }
})
