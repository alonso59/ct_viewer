// @vitest-environment jsdom
// CTF-19 (API-72): the console panel sends lines to the server session, shows the result, follows
// started work in the Output tab, completes with Tab and stays hidden on view-only links (UI-26).
import '../../i18n'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { api, ProblemError, type ConsoleCommand, type ConsoleResult } from '../../api'
import { toProblemError } from '../../api/problem'
import { registry, ShellProviders, useWorkbench } from '../../shell'
import { useLayout, useReviewer } from '../../state'
import { registerJobs } from '../jobs'
import { complete, logOf, resultLines } from './console'
import { ConsolePanel } from './ConsolePanel'
import { registerConsole } from './index'

const COMMANDS: ConsoleCommand[] = [
  { name: 'help', task_id: null, summary: 'List', usage: 'help', options: [], available: true, reason: null },
  { name: 'segment', task_id: 'segment.nnunet', summary: 'nnU-Net', usage: 'segment …', available: true, reason: null,
    options: [{ name: 'gpus', type: 'integer', help: '', enum: null, default: 1, setting: 'gpu_cap' }, { name: 'seg', type: 'string', help: '', enum: null, default: null, setting: null }] },
  { name: 'status', task_id: null, summary: 'Show', usage: 'status <id>', options: [], available: true, reason: null },
]  // prettier-ignore

const started = (over: Partial<ConsoleResult> = {}): ConsoleResult => ({
  session: 'S1',
  project_id: 'p1',
  value: 'R1',
  text: ['segment.nnunet run R1 queued (3 items)'],
  steps: [{ command: 'segment', value: 'R1', task_id: 'segment.nnunet', target: null, plan: null, work: null, data: null, text: [],
    started: { kind: 'task-run', id: 'R1', job_id: 'J1', status: 'queued', project_id: 'p1' } }],
  plan_stopped: null,
  error: null,
  ...over,
})  // prettier-ignore

let qc: QueryClient
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={qc}><ShellProviders>{children}</ShellProviders></QueryClientProvider>
}
const input = () => screen.getByLabelText('ctflow')
const type = (text: string, key = 'Enter') => {
  fireEvent.change(input(), { target: { value: text } })
  fireEvent.keyDown(input(), { key })
}

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  useWorkbench.setState({ pid: 'p1' })
  useReviewer.setState({ name: 'Dr. C', prompting: false })
  vi.spyOn(api, 'consoleCommands').mockResolvedValue(COMMANDS)
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  registry.setReadOnly(false)
  for (const c of registry.outputChannels) registry.removeOutputChannel(c.id)
  useWorkbench.setState({ pid: null })
})

test('a line runs in one server session and started work can be followed', async () => {
  registerJobs()
  const run = vi.spyOn(api, 'consoleEval').mockResolvedValue(started())
  render(<ConsolePanel />, { wrapper })
  type('segment case_00012 -gpus 2')
  expect(await screen.findByText('segment.nnunet run R1 queued (3 items)')).toBeTruthy()
  expect(run).toHaveBeenCalledWith({ line: 'segment case_00012 -gpus 2', session: null, project_id: 'p1', plan: false }, 'Dr. C')
  type('status R1')
  await waitFor(() => expect(run).toHaveBeenLastCalledWith({ line: 'status R1', session: 'S1', project_id: 'p1', plan: false }, 'Dr. C'))
  fireEvent.click(screen.getAllByRole('button', { name: 'Follow' })[0] as HTMLElement)
  expect(registry.outputChannels).toEqual([{ id: 'ctflow.R1', label: 'Console R1', kind: 'project-run', ref: 'R1', project: 'p1' }])
  expect(useLayout.getState().activePanelTab).toBe('output')
})

test('plan lines are planned, refusals show their choices, and an ended session restarts once', async () => {
  const ambiguous = toProblemError(422, { type: '/problems/validation', title: 'Invalid', detail: 'Several segmentation sets match; choose one with -seg',
    errors: [{ loc: ['option', 'seg'], msg: 'one of: a, b, default' }] }, 'x')  // prettier-ignore
  const ended = new ProblemError(404, 'not-found', 'Not found', 'session ended', ['new_session'])
  const run = vi.spyOn(api, 'consoleEval')
    .mockResolvedValueOnce(started({ text: ['plan segment: ok, ready 3 of 3'], steps: [] }))
    .mockRejectedValueOnce(ambiguous)
    .mockRejectedValueOnce(ended)
    .mockResolvedValueOnce(started({ session: 'S2', text: ['ok'], steps: [] }))  // prettier-ignore
  render(<ConsolePanel />, { wrapper })
  type('plan segment case_00012')
  expect(await screen.findByText('plan segment: ok, ready 3 of 3')).toBeTruthy()
  expect(run).toHaveBeenLastCalledWith(expect.objectContaining({ line: 'segment case_00012', plan: true }), 'Dr. C')
  type('radiomics case_00012 -labels tumor')
  expect(await screen.findByText(/one of: a, b, default/)).toBeTruthy()
  type('help')
  expect(await screen.findByText('ok')).toBeTruthy()
  expect(screen.getByText(/console session ended/)).toBeTruthy()
  expect(run.mock.calls.at(-1)?.[0]).toMatchObject({ session: null })
})

test('Tab completes commands and options from the catalog, arrows walk the history', async () => {
  vi.spyOn(api, 'consoleEval').mockResolvedValue(started({ text: ['x'], steps: [] }))
  render(<ConsolePanel />, { wrapper })
  await waitFor(() => expect(api.consoleCommands).toHaveBeenCalled())
  await new Promise((r) => setTimeout(r, 0))
  type('seg', 'Tab')
  expect((input() as HTMLInputElement).value).toBe('segment ')
  type('segment case -g', 'Tab')
  expect((input() as HTMLInputElement).value).toBe('segment case -gpus ')
  type('help')
  await screen.findByText('x')
  fireEvent.keyDown(input(), { key: 'ArrowUp' })
  expect((input() as HTMLInputElement).value).toBe('help')
})

test('the console is a write surface: hidden on view-only links', () => {
  registerConsole()
  expect(registry.panelTabs.find((p) => p.id === 'console')?.writes).toBe(true)
  registry.setReadOnly(true)
  expect(registry.allowed(registry.panelTabs.find((p) => p.id === 'console') ?? {})).toBe(false)
})

test('result lines, log kinds and completion are pure', () => {
  const lines = resultLines(started({ error: { title: 'not-found', detail: 'No case', line: 2, errors: [], actions: [] }, plan_stopped: 'status uses …' }))
  expect(lines.map((l) => l.kind)).toEqual(['out', 'note', 'note', 'err'])
  expect(lines.at(-1)?.text).toBe('not-found: line 2: No case')
  expect(logOf({ kind: 'script-run', id: 'S', job_id: null, status: 'running', project_id: null })).toEqual({ kind: 'script-run', ref: 'S' })
  expect(complete('s', COMMANDS)).toEqual({ input: 's', candidates: ['segment', 'status'] })
  expect(complete('zzz', COMMANDS)).toEqual({ input: 'zzz', candidates: [] })
})
