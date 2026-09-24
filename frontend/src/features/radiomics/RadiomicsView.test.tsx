// Runs list (RAD-06..08): live progress from the run's job, cancel/resume, failures; and FE-11
// coverage of the temporary `rad` string bundle.
import * as RTooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ComponentType } from 'react'

import '../../i18n'
import { keys, type Job } from '../../api'
import { useWorkbench } from '../../shell'
import type { RunSummary } from './model/types'

const PID = 'p1'
const posted: string[] = []

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}
const run = (over: Partial<RunSummary>): RunSummary => ({
  run_id: 'r',
  name: 'Run',
  status: 'completed',
  created_at: '2026-09-24T10:00:00Z',
  reviewer: 'AP',
  profile_hash: 'sha256:aa',
  selection: { scope: 'complete', labels: [2], item_ids: [] },
  counts: { items: 10, ok: 10, failed: 0, features: 107, skipped: 0 },
  job_id: null,
  ...over,
})
const runs = [
  run({ run_id: 'r1', name: 'Running one', status: 'running', job_id: 'j1', created_at: '2026-09-24T12:00:00Z', counts: { items: 40, ok: 0, failed: 0, features: 0, skipped: 0 } }),
  run({ run_id: 'r2', name: 'Interrupted one', status: 'interrupted', created_at: '2026-09-24T11:00:00Z' }),
  run({ run_id: 'r3', name: 'Done with errors', status: 'completed_with_errors', counts: { items: 10, ok: 8, failed: 1, features: 107, skipped: 1 } }),
]
const jobs = [{ job_id: 'j1', kind: 'radiomics', project_id: PID, status: 'running', done: 10, total: 40, eta_s: 90, ref: 'r1' }] as unknown as Job[]

async function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const req = input instanceof Request ? input : new Request(input, init)
  const p = new URL(req.url).pathname.replace('/api/v1', '')
  if (req.method === 'POST') posted.push(p)
  if (p === `/projects/${PID}/radiomics/runs`) return reply(200, { items: runs, total: runs.length })
  if (p === `/projects/${PID}/radiomics/profiles`) return reply(200, { items: [], total: 0 })
  if (p === `/projects/${PID}/radiomics/runs/r3/errors`)
    return reply(200, {
      items: [
        { item_id: 'case_1.01.complete.-', label: 2, kind: 'failed', error: 'input: item has no mask', at: '2026-09-24T10:00:01Z' },
        { item_id: 'case_2.01.complete.-', label: 2, kind: 'skipped', error: 'label absent', at: '2026-09-24T10:00:02Z' },
      ],
      total: 2,
    })
  if (p.endsWith('/cancel') || p.endsWith('/resume')) return reply(200, runs[0])
  return reply(404, { type: '/problems/not-found', title: 'Not found', status: 404 })
}

let View: ComponentType
let RAD_EN: Record<string, unknown>
beforeAll(async () => {
  vi.stubEnv('VITE_API_BASE', 'http://api.test')
  vi.stubGlobal('fetch', fakeFetch)
  View = (await import('./RadiomicsView')).RadiomicsView
  // Strings split between the eager and lazy bundles (NFR-07); both are loaded in the app
  RAD_EN = { ...(await import('../../i18n/en.json')).default.rad, ...(await import('../../i18n/en.lazy.json')).default.rad }
})
afterAll(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

function setup() {
  useWorkbench.setState({ pid: PID })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.jobs(PID), jobs)
  render(
    <QueryClientProvider client={qc}>
      <RTooltip.Provider>
        <View />
      </RTooltip.Provider>
    </QueryClientProvider>,
  )
}

const row = (name: string) => screen.getByText(name).closest('li') as HTMLElement

test('runs show status, live job progress with ETA, and the matching controls', async () => {
  setup()
  await screen.findByText('Running one')
  const names = within(screen.getByRole('list', { name: 'Runs' })).getAllByRole('listitem').map((li) => li.querySelector('.rad-run-name')?.textContent)
  expect(names).toEqual(['Running one', 'Interrupted one', 'Done with errors'])

  const r1 = row('Running one')
  expect(within(r1).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '25')
  expect(r1).toHaveTextContent('10/40 · 1 min 30 s left')
  fireEvent.click(within(r1).getByRole('button', { name: 'Cancel run' }))
  await waitFor(() => expect(posted).toContain(`/projects/${PID}/radiomics/runs/r1/cancel`))

  const r2 = row('Interrupted one')
  expect(within(r2).queryByRole('progressbar')).toBeNull()
  fireEvent.click(within(r2).getByRole('button', { name: 'Resume run' }))
  await waitFor(() => expect(posted).toContain(`/projects/${PID}/radiomics/runs/r2/resume`))

  const r3 = row('Done with errors')
  expect(r3).toHaveTextContent('8/10 ok · 107 features')
  expect(r3).toHaveTextContent('1 failed')
  expect(r3).toHaveTextContent('1 skipped')
  expect(within(r3).getByRole('link', { name: 'Export CSV (wide)' })).toHaveAttribute('href', expect.stringContaining('/runs/r3/features?format=csv&shape=wide'))
  fireEvent.click(within(r3).getByRole('button', { name: 'Show failures' }))
  expect(await screen.findByText('input: item has no mask')).toBeInTheDocument()
  expect(screen.getByText('Skipped')).toBeInTheDocument()
})

// FE-11: every `rad.*` key used by the feature exists in the bundle (the shared key test only
// covers namespaces present in en.json)
const sources = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

test('rad.* keys exist', () => {
  const has = (key: string) => {
    let node: unknown = { rad: RAD_EN }
    const parts = key.split('.')
    parts.forEach((p, i) => {
      const n = node as Record<string, unknown> | undefined
      node = n?.[p] ?? (i === parts.length - 1 ? (n?.[`${p}_other`] ?? n?.[`${p}_one`]) : undefined)
    })
    return typeof node === 'string'
  }
  const missing = new Set<string>()
  for (const [file, src] of Object.entries(sources))
    for (const m of src.matchAll(/'(rad\.[a-zA-Z0-9_.]+)'/g)) if (!has(m[1] ?? '')) missing.add(`${m[1]} (${file})`)
  expect([...missing]).toEqual([])
  // Dynamic families
  const families: [string, string[]][] = [
    ['itemsMode', ['all', 'filter', 'list']],
    ['itemsHelp', ['all', 'filter', 'list']],
    ['scopeName', ['complete', 'voi']],
    ['sideName', ['L', 'R', 'none']],
    ['errKindName', ['failed', 'skipped']],
    ['rule', ['required', 'number', 'integer', 'list', 'choice', 'range', 'gt', 'ge', 'lt', 'le', 'count', 'countRange', 'spacing', 'binXor', 'logSigma', 'force2d', 'resegOrder', 'resegSigma', 'nothing', 'normalizeHu', 'unavailable']],
  ]
  expect(families.flatMap(([ns, vs]) => vs.map((v) => `rad.${ns}.${v}`)).filter((k) => !has(k))).toEqual([])
})
