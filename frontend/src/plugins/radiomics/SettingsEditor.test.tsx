// Settings tab against a stubbed API-30..37 (real engine schema fixture): engine defaults on open
// (RAD-01/02), live + server validation gating Run (RAD-04), selection (RAD-05), estimate
// (RAD-11), profiles (RAD-03) and the run request (RAD-06).
import * as RTooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ComponentType } from 'react'

import '../../i18n'
import { keys, type Project, type Variable } from '../../api'
import { useWorkbench } from '../../shell'
import { useReviewer } from '../../state'
import schemaJson from './model/fixtures/schema.json'
import type { SettingsSchema } from './model/types'

// Bind the HTTP client (unit tests default to the mock) against the fake fetch below
vi.hoisted(() => vi.stubEnv('VITE_API_BASE', 'http://api.test'))
vi.mock('../../api/client', async () => ({ api: (await import('../../api/http')).httpApi, API_MODE: 'http' }))

const schema = schemaJson as unknown as SettingsSchema
const PID = 'p1'

type Call = { method: string; path: string; body: unknown; headers: Headers }
const calls: Call[] = []
let validateReply: (body: { settings: { settings?: Record<string, unknown> } }) => unknown = () => ({ ok: true, issues: [], profile_hash: 'sha256:aa' })
const profiles = [
  {
    profile_hash: 'sha256:bbbbbbbbbbbb',
    name: 'Coarse bins',
    created_at: '2026-09-20T10:00:00Z',
    updated_at: '2026-09-20T10:00:00Z',
    engine: { name: 'pyradiomics', version: '3.1', major: '3' },
    settings: { ...schema.defaults, settings: { ...schema.defaults.settings, binWidth: 50 } },
  },
]

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

async function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const req = input instanceof Request ? input : new Request(input, init)
  const url = new URL(req.url)
  const text = req.method === 'GET' ? '' : await req.text()
  const body: unknown = text ? JSON.parse(text) : null
  calls.push({ method: req.method, path: url.pathname, body, headers: req.headers })
  const p = url.pathname.replace('/api/v1', '')
  if (p === '/radiomics/schema') return reply(200, schema)
  if (p === '/radiomics/validate') return reply(200, validateReply(body as never))
  if (p === `/projects/${PID}/radiomics/profiles`) return req.method === 'GET' ? reply(200, { items: profiles, total: 1 }) : reply(201, profiles[0])
  if (p === `/projects/${PID}/radiomics/estimate`)
    return reply(200, { n_items: 12, n_labels: 1, n_units: 12, n_skipped: 1, sample_item_ids: [], time_per_item_s: 2, time_per_unit_s: 2, workers: 2, estimated_total_s: 12, sample_errors: [] })
  if (p === `/projects/${PID}/radiomics/runs` && req.method === 'POST') return reply(202, { run_id: 'r1', name: (body as { name: string }).name })
  if (p === `/projects/${PID}/radiomics/runs`) return reply(200, { items: [], total: 0 })
  return reply(404, { type: '/problems/not-found', title: 'Not found', status: 404 })
}

let Editor: ComponentType
beforeAll(async () => {
  vi.stubEnv('VITE_API_BASE', 'http://api.test')
  vi.stubGlobal('fetch', fakeFetch)
  Editor = (await import('./SettingsEditor')).SettingsEditor
})
afterAll(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

const project = {
  project_id: PID,
  name: 'P',
  phase_vocabulary: ['NC', 'NP'],
  label_map: [
    { value: 1, name: 'kidney', color: '#00FFFF', opacity: 0.2, visible: false },
    { value: 2, name: 'tumor', color: '#FFFF00', opacity: 0.2, visible: true },
  ],
} as unknown as Project
const variables = [
  { name: 'sex', type: 'categorical', profile: { missing_pct: 0, n_distinct: 2, examples: [], levels: [{ value: 'F', count: 5 }, { value: 'M', count: 7 }] } },
  { name: 'modality', type: 'categorical', profile: { missing_pct: 0, n_distinct: 2, examples: [], levels: [{ value: 'CT', count: 11 }, { value: 'MR', count: 1 }] } },
  { name: 'age', type: 'continuous', profile: { missing_pct: 0, n_distinct: 12, examples: [] } },
] as unknown as Variable[]

async function setup() {
  const { useDraft } = await import('./store')
  useDraft.setState({ pid: null, form: null })
  calls.length = 0
  validateReply = () => ({ ok: true, issues: [], profile_hash: 'sha256:aa' })
  useWorkbench.setState({ pid: PID })
  useReviewer.setState({ name: 'Tester' })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.project(PID), project)
  qc.setQueryData(keys.variables(PID), variables)
  render(
    <QueryClientProvider client={qc}>
      <RTooltip.Provider>
        <Editor />
      </RTooltip.Provider>
    </QueryClientProvider>,
  )
  await screen.findByRole('navigation', { name: 'Setting groups' })
}

const nav = (name: string) => within(screen.getByRole('navigation', { name: 'Setting groups' })).getByRole('button', { name: new RegExp(`^${name}`) })
const runButton = () => screen.getByRole('button', { name: 'Run extraction' })
const settle = () => act(() => new Promise((r) => setTimeout(r, 400)))

test('opens on the engine defaults from the schema', async () => {
  await setup()
  // Groups come from the schema, in its order
  expect(nav('Discretization')).toBeInTheDocument()
  fireEvent.click(nav('Discretization'))
  // AUD-A3-04: number fields are text fields that show a point (the value is the typed text)
  expect(screen.getByLabelText('binWidth')).toHaveValue('25')
  expect(screen.getByLabelText('binCount')).toHaveValue('')
  expect(screen.getByTestId('default-binWidth')).toHaveTextContent('Default: 25')

  fireEvent.click(nav('Filters'))
  expect(screen.getByRole('checkbox', { name: 'Original' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Wavelet' })).not.toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'LBP3D' })).toBeDisabled()

  fireEvent.click(nav('Feature classes'))
  expect(screen.getByRole('checkbox', { name: 'shape2D' })).not.toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'firstorder' })).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'firstorder' }))
  // Deprecated StandardDeviation is off by default, the rest on
  expect(screen.getByRole('checkbox', { name: /StandardDeviation/ })).not.toBeChecked()
  expect(screen.getByRole('checkbox', { name: /^Entropy/ })).toBeChecked()

  // Default label = first visible label
  fireEvent.click(nav('Selection'))
  expect(screen.getByRole('checkbox', { name: /tumor/ })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: /kidney/ })).not.toBeChecked()
})

test('live validation disables Run; the server answer then takes over', async () => {
  await setup()
  validateReply = (b) =>
    b.settings.settings?.binCount != null
      ? { ok: false, issues: [{ loc: ['settings', 'binCount'], msg: 'Server says: pick one', severity: 'error', rule: 'bin_xor' }] }
      : { ok: true, issues: [], profile_hash: 'sha256:aa' }
  await settle()
  expect(runButton()).toBeEnabled()
  fireEvent.click(nav('Discretization'))
  fireEvent.change(screen.getByLabelText('binCount'), { target: { value: '32' } })
  // Client rule, before the server answers
  expect(runButton()).toBeDisabled()
  expect(screen.getAllByText('Choose bin width or bin count').length).toBeGreaterThan(0)
  await waitFor(() => expect(screen.getAllByText('Server says: pick one').length).toBeGreaterThan(0))
  expect(runButton()).toBeDisabled()
  expect(nav('Discretization')).toHaveTextContent('1')
  // Clearing fixes it
  fireEvent.change(screen.getByLabelText('binCount'), { target: { value: '' } })
  await waitFor(() => expect(runButton()).toBeEnabled())
  expect(screen.getByText('Settings are valid')).toBeInTheDocument()
})

test('a sigma-less LoG and a 2D-only class are flagged in their groups', async () => {
  await setup()
  fireEvent.click(nav('Filters'))
  fireEvent.click(screen.getByRole('checkbox', { name: 'LoG' }))
  expect(screen.getAllByText('LoG needs at least one sigma').length).toBeGreaterThan(0)
  fireEvent.click(nav('Feature classes'))
  fireEvent.click(screen.getByRole('checkbox', { name: 'shape2D' }))
  expect(screen.getAllByText('Enable 2D mode for this option').length).toBeGreaterThan(0)
  expect(runButton()).toBeDisabled()
})

test('selection by variable feeds the estimate and the run request', async () => {
  await setup()
  fireEvent.click(screen.getByRole('radio', { name: 'Filter by variable' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'NP' }))
  fireEvent.change(screen.getByLabelText('Variable'), { target: { value: 'sex' } })
  fireEvent.click(screen.getByRole('checkbox', { name: /^F/ }))
  // Continuous variables are explained, not offered
  expect(screen.queryByRole('option', { name: 'age' })).toBeNull()
  // The project has MR images: the CT-defaults warning shows until modality is restricted to CT
  expect(screen.getByText(/defaults assume CT/)).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Estimate time' }))
  const est = await screen.findByTestId('estimate')
  expect(est).toHaveTextContent('12 items × 1 labels = 12 extractions')
  expect(est).toHaveTextContent('1 extraction will be skipped')
  const estCall = calls.find((c) => c.path.endsWith('/radiomics/estimate'))
  expect(estCall?.body).toMatchObject({ selection: { scope: 'complete', labels: [2], filter: { phase: ['NP'], var: { sex: ['F'] } } } })

  await settle()
  fireEvent.click(runButton())
  const isRun = (c: Call) => c.method === 'POST' && c.path.endsWith('/radiomics/runs')
  await waitFor(() => expect(calls.some(isRun)).toBe(true))
  const run = calls.find(isRun)
  expect(run?.headers.get('x-reviewer')).toBe('Tester')
  const body = run?.body as { name: string; settings: typeof schema.defaults; selection: unknown }
  expect(body.name).toBe('Run · engine defaults')
  expect(body.selection).toEqual({ scope: 'complete', labels: [2], filter: { phase: ['NP'], var: { sex: ['F'] } } })
  expect(Object.keys(body.settings.image_types ?? {})).toEqual(['Original'])
  expect(body.settings.features).toEqual(schema.defaults.features)
  expect(body.settings.settings).toMatchObject({ binWidth: 25, binCount: null })
})

test('an empty explicit list is "Nothing to extract"', async () => {
  await setup()
  fireEvent.click(screen.getByRole('radio', { name: 'Explicit list' }))
  expect(runButton()).toBeDisabled()
  expect(screen.getAllByText('Nothing to extract').length).toBeGreaterThan(0)
  fireEvent.change(screen.getByLabelText('Item ids'), { target: { value: 'case_1.01.complete.-\ncase_2.01.complete.-' } })
  expect(screen.getByText('2 items')).toBeInTheDocument()
  await waitFor(() => expect(runButton()).toBeEnabled())
})

test('loading a profile fills the form; engine defaults restore it', async () => {
  await setup()
  const picker = screen.getByLabelText('Load profile…')
  await waitFor(() => expect(within(picker).getAllByRole('option')).toHaveLength(2))
  fireEvent.change(picker, { target: { value: 'sha256:bbbbbbbbbbbb' } })
  fireEvent.click(nav('Discretization'))
  expect(screen.getByLabelText('binWidth')).toHaveValue('50')
  fireEvent.click(screen.getByRole('button', { name: 'Engine defaults' }))
  expect(screen.getByLabelText('binWidth')).toHaveValue('25')
})
