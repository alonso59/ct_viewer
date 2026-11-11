// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { api, type ComputeProfile, type ComputeState, type StorageLocation, type StorageState } from '../../api'
import { ComputeDialog } from './ComputeDialog'
import { StorageDialog } from './StorageDialog'

afterEach(() => vi.restoreAllMocks())

const wrap = (node: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>)
const DAY = 86_400

const location = (over: Partial<StorageLocation>): StorageLocation => ({
  id: 'l1',
  kind: 'local_directory',
  path: '/data/scans',
  access: 'read_write',
  label: '',
  workspace: null,
  available: true,
  readable: true,
  writable: true,
  remaining_seconds: null,
  projects: [],
  ...over,
})
const storage = (over: Partial<StorageState>): StorageState => ({
  locations: [],
  default_location: null,
  registrable: true,
  allowed_roots: ['/data'],
  discovered: null,
  discovery_error: null,
  ...over,
})

test('a workspace close to expiry warns and offers the extend command; nothing is run for the user', async () => {
  const workspace = { name: 'scans', filesystem: 'scratch', expires: '2026-12-01T00:00:00Z', extensions: 2, observed_at: null }
  vi.spyOn(api, 'getStorage').mockResolvedValue(
    storage({
      locations: [
        location({ kind: 'managed_hpc_workspace', workspace, remaining_seconds: 3 * DAY + 60, projects: ['Study'] }),
        location({ id: 'l2', path: '/data/atlas', access: 'read_only', writable: false }),
        location({ id: 'l3', path: '/lustre/gone', available: false, readable: false, writable: false }),
      ],
      default_location: 'l1',
    }),
  )
  const register = vi.spyOn(api, 'registerLocation')
  wrap(<StorageDialog onClose={() => undefined} />)
  const rows = await screen.findAllByRole('listitem')
  const [ws, atlas, gone] = rows as [HTMLElement, HTMLElement, HTMLElement]
  expect(within(ws).getByText('Expires in 3 days')).toHaveAttribute('data-tone', 'warn')
  expect(within(ws).getByText('ws_extend -F scratch scans 30')).toBeInTheDocument()
  expect(within(ws).getByText('Projects here: Study')).toBeInTheDocument()
  expect(within(ws).getByText('Default for new projects')).toBeInTheDocument()
  expect(within(atlas).queryByRole('button', { name: 'Use for new projects' })).toBeNull()
  expect(within(gone).getByText('Unavailable')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
  expect(register).not.toHaveBeenCalled()
})

test('without operator folders nothing can be added; without a workspace tool no workspace section shows', async () => {
  vi.spyOn(api, 'getStorage').mockResolvedValue(storage({ registrable: false }))
  wrap(<StorageDialog onClose={() => undefined} />)
  expect(await screen.findByText(/The operator has allowed no folders/)).toBeInTheDocument()
  expect(screen.queryByText('Your cluster workspaces')).toBeNull()
})

test('a discovered workspace outside the allowed folders cannot be used', async () => {
  const discovered = [
    { name: 'in', path: '/data/in', filesystem: 'scratch', expires: null, extensions: 3, observed_at: null, blocked: '' },
    { name: 'out', path: '/lustre/out', filesystem: 'scratch', expires: null, extensions: 3, observed_at: null, blocked: 'outside' },
  ]
  vi.spyOn(api, 'getStorage').mockResolvedValue(storage({ discovered }))
  wrap(<StorageDialog onClose={() => undefined} />)
  expect(await screen.findByText('Outside the folders the operator allows')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Use' })).toHaveLength(1)
  expect(screen.getByText('ws_allocate -F scratch rw-data 30')).toBeInTheDocument()
})

const profile = (over: Partial<ComputeProfile>): ComputeProfile => ({
  id: 'a100',
  name: 'One A100',
  account: 'lab',
  partition: 'gpu_short',
  gpus: 1,
  cpus: 8,
  memory_mb: 16384,
  seconds: 28800,
  status: 'valid',
  reason: '',
  checked_at: null,
  estimated_start: null,
  implicit: false,
  ...over,
})
const compute = (over: Partial<ComputeState>): ComputeState => ({
  backend: 'slurm',
  limits: { cpus: 8, memory_mb: 32768, tasks: 64, seconds: 86400, gpus: 2 },
  read_at: null,
  error: null,
  accounts: null,
  partitions: null,
  answered: null,
  profiles: [],
  ...over,
})

test('without a scheduler runner the dialog says so instead of guessing', async () => {
  vi.spyOn(api, 'getCompute').mockResolvedValue(compute({ backend: null, limits: null }))
  wrap(<ComputeDialog onClose={() => undefined} />)
  expect(await screen.findByText(/No runner reports a scheduler/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Add profile' })).toBeNull()
})

test('unknown scheduler facts read as unknown; verdicts come from the runner', async () => {
  vi.spyOn(api, 'getCompute').mockResolvedValue(
    compute({
      profiles: [
        profile({ estimated_start: '2026-11-12T10:00:00' }),
        profile({ id: 'big', name: 'Too long', status: 'rejected', reason: 'time limit exceeded' }),
      ],
    }),
  )
  wrap(<ComputeDialog onClose={() => undefined} />)
  expect(await screen.findByText(/Your accounts are unknown/)).toBeInTheDocument()
  expect(screen.getByText(/Partitions are unknown/)).toBeInTheDocument()
  expect(screen.getByText(/Scheduler estimate: start/)).toBeInTheDocument()
  expect(screen.getByText('time limit exceeded')).toBeInTheDocument()
  expect(screen.getByText(/up to 8 CPUs, 32 GiB, 24 h and 2 GPUs/)).toBeInTheDocument()
})

test('a new profile uses the discovered lists and never asks for more than two GPUs', async () => {
  vi.spyOn(api, 'getCompute').mockResolvedValue(
    compute({ accounts: ['lab'], partitions: [{ name: 'gpu_short', up: true, max_seconds: 28800, gpus: true, gpu_types: ['a100'] }] }),
  )
  const put = vi.spyOn(api, 'putComputeProfile').mockResolvedValue(compute({}))
  wrap(<ComputeDialog onClose={() => undefined} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Add profile' }))
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Small GPU' } })
  expect(screen.getByLabelText('Account')).toHaveValue('lab')
  expect(screen.getByLabelText('Partition')).toHaveValue('gpu_short')
  expect(screen.getByText(/longest time/)).toHaveTextContent('GPU types a100')
  expect(screen.getByText('GPUs (up to 2)')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(put).toHaveBeenCalled())
  const [id, body] = put.mock.calls[0]!
  expect(id).toBe('small-gpu')
  expect(body).toMatchObject({ name: 'Small GPU', account: 'lab', partition: 'gpu_short', gpus: 1, seconds: 28800 })
})

test('a new profile never replaces one whose name gives the same id', async () => {
  vi.spyOn(api, 'getCompute').mockResolvedValue(compute({ profiles: [profile({ id: 'gpu-large', name: 'GPU large' })] }))
  const put = vi.spyOn(api, 'putComputeProfile').mockResolvedValue(compute({}))
  wrap(<ComputeDialog onClose={() => undefined} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Add profile' }))
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'gpu_large' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(put).toHaveBeenCalled())
  expect(put.mock.calls[0]![0]).toBe('gpu-large-2')
})

test('Check now waits for the runner to answer this request', async () => {
  vi.spyOn(api, 'checkCompute').mockResolvedValue({ request: 'r2' })
  const get = vi
    .spyOn(api, 'getCompute')
    .mockResolvedValueOnce(compute({ answered: 'r1' }))
    .mockResolvedValueOnce(compute({ answered: 'r1' }))
    .mockResolvedValue(compute({ answered: 'r2', read_at: new Date().toISOString() }))
  wrap(<ComputeDialog onClose={() => undefined} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Check now' }))
  expect(await screen.findByRole('button', { name: 'Checking…' })).toBeDisabled()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check now' })).toBeEnabled(), { timeout: 5000 })
  expect(get.mock.calls.length).toBeGreaterThanOrEqual(3)
})
