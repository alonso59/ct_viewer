// @vitest-environment jsdom
// UI-29 (API-71): output channels, the output.show command and the polled log stream.
import '../../i18n'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { api, useLogStream, type LogPage } from '../../api'
import { registry, runCommand, ShellProviders, useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { registerJobs, showOutput } from './index'
import { ACTIVITY, OutputDock, useOutputView } from './Output'

const page = (texts: string[], next_cursor: string, done = false): LogPage => ({
  lines: texts.map((text) => ({ ts: null, level: 'info', stream: 'log', text })),
  next_cursor,
  done,
})

let qc: QueryClient
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={qc}><ShellProviders>{children}</ShellProviders></QueryClientProvider>
}

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  registerJobs()
  useOutputView.setState({ channel: ACTIVITY, docked: false })
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.useRealTimers()
  for (const c of registry.outputChannels) registry.removeOutputChannel(c.id)
  useWorkbench.setState({ pid: null })
})

test('channels upsert by id and can be removed', () => {
  const seen = vi.fn()
  const off = registry.subscribeOutputChannels(seen)
  registry.outputChannel({ id: 'a', label: 'A', kind: 'source-operation', ref: '1' })
  registry.outputChannel({ id: 'b', label: 'B', kind: 'workspace-run', ref: '2' })
  registry.outputChannel({ id: 'a', label: 'A2', kind: 'workspace-run', ref: '3' })
  expect(registry.outputChannels.map((c) => [c.id, c.label, c.ref])).toEqual([['a', 'A2', '3'], ['b', 'B', '2']])
  registry.removeOutputChannel('a')
  expect(registry.outputChannels.map((c) => c.id)).toEqual(['b'])
  expect(seen).toHaveBeenCalledTimes(4)
  off()
})

test('output.show selects the channel on the project panel, or docks the panel outside projects', () => {
  useWorkbench.setState({ pid: 'p1' })
  useLayout.setState({ panelVisible: false, activePanelTab: 'jobs' })
  runCommand('output.show', 'x')
  expect(useLayout.getState()).toMatchObject({ panelVisible: true, activePanelTab: 'output' })
  expect(useOutputView.getState()).toMatchObject({ channel: 'x', docked: false })

  useWorkbench.setState({ pid: null })
  vi.spyOn(api, 'readLogs').mockResolvedValue(page(['hello'], 'c1', true))
  render(<OutputDock />, { wrapper })
  expect(screen.queryByRole('log')).toBeNull()
  act(() => showOutput({ id: 'op', label: 'ds · output', kind: 'source-operation', ref: 'r1' }))
  expect(useOutputView.getState()).toMatchObject({ channel: 'op', docked: true })
  expect(screen.getByRole('combobox', { name: 'Log channel' })).toHaveProperty('value', 'op')
  expect(screen.getByRole('option', { name: 'Activity' })).toBeTruthy()
})

test('the log stream follows the cursor and stops polling once done', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const read = vi.spyOn(api, 'readLogs')
    .mockResolvedValueOnce(page(['one'], 'c1'))
    .mockResolvedValueOnce(page(['two'], 'c2', true))
  const { result } = renderHook(() => useLogStream('workspace-run', 'r1'), { wrapper })
  await waitFor(() => expect(result.current.data?.lines.map((l) => l.text)).toEqual(['one']))
  await act(() => vi.advanceTimersByTimeAsync(1100))
  await waitFor(() => expect(result.current.data?.done).toBe(true))
  expect(result.current.data?.lines.map((l) => l.text)).toEqual(['one', 'two'])
  expect(read.mock.calls).toEqual([['workspace-run', 'r1', undefined], ['workspace-run', 'r1', 'c1']])
  await act(() => vi.advanceTimersByTimeAsync(3000))
  expect(read).toHaveBeenCalledTimes(2)
})
