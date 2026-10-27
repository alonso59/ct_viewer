// @vitest-environment jsdom
// TSK-06: native failure details notify once per attempt, without replaying old errors.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, waitFor } from '@testing-library/react'

import '../../i18n'
import { keys, type TaskRunSummary } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { TaskCommands } from './index'

const run = { run_id: 'run', job_id: 'job', name: 'Kidney segmentation', status: 'running', task: { id: 'segment.nnunet' }, error: null } as TaskRunSummary

afterEach(() => useWorkbench.setState({ pid: null, toasts: [] }))

function show(initial: TaskRunSummary) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(keys.tasks(), { tasks: [], invalid: [], runners: [] })
  client.setQueryData(keys.taskRuns(DEMO_PID), [initial])
  useWorkbench.setState({ pid: DEMO_PID, toasts: [] })
  render(<QueryClientProvider client={client}><TaskCommands /></QueryClientProvider>)
  return client
}

test('CUDA out of memory is notified once with a task-details action', async () => {
  const client = show(run)
  const failed = { ...run, status: 'failed', error: 'CUDA out of memory. Choose GPUs with more free memory, then resume.' }
  act(() => client.setQueryData(keys.taskRuns(DEMO_PID), [failed]))
  await waitFor(() => expect(useWorkbench.getState().toasts).toHaveLength(1))
  const notice = useWorkbench.getState().toasts[0]!
  expect(notice.message).toContain('CUDA out of memory')
  expect(notice.message).toContain(run.name)
  expect(notice.action?.label).toBe('Show task')
  act(() => client.setQueryData(keys.taskRuns(DEMO_PID), [{ ...failed }]))
  expect(useWorkbench.getState().toasts).toHaveLength(1)
})

test('opening a project does not replay a previous failure notification', () => {
  show({ ...run, status: 'failed', error: 'CUDA out of memory' })
  expect(useWorkbench.getState().toasts).toHaveLength(0)
})

test('a newly submitted run that fails before its first refresh still notifies', async () => {
  const client = show(run)
  act(() => client.setQueryData(keys.taskRuns(DEMO_PID), [run, { ...run, run_id: 'new-run', job_id: 'new-job', status: 'failed', error: 'CUDA out of memory' }]))
  await waitFor(() => expect(useWorkbench.getState().toasts).toHaveLength(1))
})
