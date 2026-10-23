// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { api, type TaskInfo } from '../../api'
import { GpuAvailability } from './GpuAvailability'

afterEach(() => vi.restoreAllMocks())

test('checking waits for a new runner sample without starting any task', async () => {
  const template = (await api.listTasks()).tasks[0]!
  const info = (at: string): TaskInfo => ({ ...template, manifest: { ...template.manifest, id: 'segment.nnunet' }, runner_online: true, execution: { inventory: { at, devices: [{ busy: false }, { busy: true }] } } })
  const before = info('2026-10-22T18:00:00Z')
  const fresh = info('2026-10-22T18:00:10Z')
  const list = vi.spyOn(api, 'listTasks').mockResolvedValueOnce({ tasks: [before], invalid: [], runners: [] }).mockResolvedValue({ tasks: [fresh], invalid: [], runners: [] })
  const start = vi.spyOn(api, 'startTaskRun')
  render(<QueryClientProvider client={new QueryClient()}><GpuAvailability info={before} /></QueryClientProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Check GPUs' }))
  expect(await screen.findByRole('button', { name: 'Checking GPUs…' })).toBeDisabled()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check GPUs' })).toBeEnabled(), { timeout: 4000 })
  expect(list).toHaveBeenCalledTimes(2)
  expect(start).not.toHaveBeenCalled()
})
