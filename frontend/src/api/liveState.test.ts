// CUR-11/12, TST-08, AUD-A6-04: the API-40 handler (`applyServerEvent`) against a real QueryClient,
// and the SSE stream's reconnect signal (AUD-A5-11).
import { QueryClient, QueryObserver } from '@tanstack/react-query'
import { afterEach, expect, test, vi } from 'vitest'

import { applyServerEvent, upsertStateRow } from './hooks'
import { httpApi } from './http'
import { keys } from './keys'
import type { CurationEvent, CurationStateRow, Job, ServerEvent } from './types'

const ev = (id: string, status: CurationEvent['status'], reviewer: string, seg_id: string | null = 'imported') =>
  ({ event_id: id, item_id: 'i1', case_id: 'c1', target: 'seg', seg_id, status, priority: 'medium', comment: '', reviewer, at: '2026-09-25T00:00:00Z', add_to_queue: false }) as CurationEvent
const appended = (e: CurationEvent): ServerEvent => ({ event: 'curation.appended', data: e })
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
const tick = () => new Promise((r) => setTimeout(r, 0))

afterEach(() => vi.unstubAllGlobals())

test('upsert replaces the row of the same (item, target, seg_id) and ignores a replayed event', () => {
  const other: CurationStateRow = { ...upsertStateRow([], ev('e0', 'accepted', 'x'))[0]!, target: 'side', seg_id: null, event_id: 'p' }
  let rows = upsertStateRow([other], ev('e1', 'accepted', 'Dr. A'))
  expect(rows.map((r) => [r.target, r.status])).toEqual([['side', 'accepted'], ['seg', 'accepted']])
  rows = upsertStateRow(rows, ev('e2', 'rejected', 'Dr. B'))
  expect(rows.filter((r) => r.target === 'seg').map((r) => [r.status, r.reviewer])).toEqual([['rejected', 'Dr. B']])
  expect(upsertStateRow(rows, ev('e2', 'rejected', 'Dr. B'))).toBe(rows)
  // AUD-A5-06: another set's decision is its own row; an event without seg_id is `imported`
  rows = upsertStateRow(rows, ev('e3', 'accepted', 'Dr. C', 'thr'))
  expect(rows.filter((r) => r.target === 'seg').map((r) => [r.seg_id, r.status])).toEqual([['imported', 'rejected'], ['thr', 'accepted']])
  rows = upsertStateRow(rows, ev('e4', 'missing', 'Dr. C', null))
  expect(rows.filter((r) => r.target === 'seg').map((r) => [r.seg_id, r.status])).toEqual([['thr', 'accepted'], ['imported', 'missing']])
})

test('AUD-A0-02: an event during the first curation/state fetch is not lost', async () => {
  const qc = client()
  let calls = 0
  let releaseFirst: (rows: CurationStateRow[]) => void = () => undefined
  const fresh = upsertStateRow([], ev('e1', 'accepted', 'Dr. A'))
  const obs = new QueryObserver(qc, {
    queryKey: keys.curationState('p'),
    queryFn: () => (++calls === 1 ? new Promise<CurationStateRow[]>((r) => (releaseFirst = r)) : Promise.resolve(fresh)),
  })
  const unsub = obs.subscribe(() => undefined)
  await tick()
  expect(calls).toBe(1) // first load in flight, cache empty
  applyServerEvent(qc, 'p', appended(ev('e1', 'accepted', 'Dr. A')))
  releaseFirst([]) // the stale answer, read before the event
  await vi.waitFor(() => expect(qc.getQueryData<CurationStateRow[]>(keys.curationState('p'))?.map((r) => r.status)).toEqual(['accepted']))
  expect(calls).toBe(2)
  unsub()
})

test('CUR-11: with a cached state the event shows at once, per set, then refetches', async () => {
  const qc = client()
  const base = upsertStateRow([], ev('e0', 'accepted', 'Dr. A'))
  qc.setQueryData(keys.curationState('p'), base)
  const cases = new QueryObserver(qc, { queryKey: keys.cases('p'), queryFn: async () => [] })
  const unsub = cases.subscribe(() => undefined)
  await tick()
  applyServerEvent(qc, 'p', appended(ev('e1', 'rejected', 'Dr. B', 'thr')))
  const rows = qc.getQueryData<CurationStateRow[]>(keys.curationState('p')) ?? []
  expect(rows.map((r) => [r.seg_id, r.status])).toEqual([['imported', 'accepted'], ['thr', 'rejected']])
  expect(qc.getQueryState(keys.curationState('p'))?.isInvalidated).toBe(true)
  expect(qc.getQueryState(keys.cases('p'))?.isInvalidated || qc.getQueryState(keys.cases('p'))?.fetchStatus === 'fetching').toBe(true)
  unsub()
})

test('job.finished merges into the jobs cache; phase.appended and reset invalidate the project', () => {
  const qc = client()
  const job = { job_id: 'j1', kind: 'index', status: 'running', done: 1, total: 2 } as Job
  qc.setQueryData(keys.jobs('p'), [job])
  applyServerEvent(qc, 'p', { event: 'job.finished', data: { job_id: 'j1', kind: 'index', status: 'succeeded', ref: null } } as ServerEvent)
  const jobs = qc.getQueryData<Job[]>(keys.jobs('p')) ?? []
  expect(jobs[0]?.status).toBe('succeeded')
  expect(jobs[0]?.finished_at).toBeTruthy()

  qc.setQueryData(keys.cases('p'), [])
  applyServerEvent(qc, 'p', { event: 'phase.appended', data: {} } as ServerEvent)
  expect(qc.getQueryState(keys.cases('p'))?.isInvalidated).toBe(true)

  qc.setQueryData(keys.labelTables('p'), [])
  qc.setQueryData(keys.projects(), [])
  applyServerEvent(qc, 'p', { event: 'reset', data: {} })
  expect(qc.getQueryState(keys.labelTables('p'))?.isInvalidated).toBe(true)
  expect(qc.getQueryState(keys.projects())?.isInvalidated).toBe(true)
})

test('AUD-A5-11: the stream reports a reopen after an error as `reset`', () => {
  const made: FakeES[] = []
  class FakeES {
    static CLOSED = 2
    readyState = 1
    onopen: (() => void) | null = null
    onerror: (() => void) | null = null
    constructor() {
      made.push(this)
    }
    addEventListener() {}
    close() {}
  }
  vi.stubGlobal('EventSource', FakeES)
  const got: string[] = []
  const states: string[] = []
  const off = httpApi.subscribe('p-reset', (e) => got.push(e.event), (s) => states.push(s))
  const es = made[0]!
  es.onopen?.()
  expect(got).toEqual([]) // the first open is not a gap
  es.onerror?.()
  es.onopen?.()
  expect(got).toEqual(['reset'])
  expect(states).toEqual(['connecting', 'live', 'connecting', 'live'])
  off()
})

// AUD-A1-04: a command's fetch survives a live-sync invalidation that cancels the fetch it joined
// (a plain `fetchQuery` rejects with CancelledError there, and "Next unreviewed" did nothing)
test('fetchSettled retries a fetch cancelled by an invalidation', async () => {
  const { fetchSettled } = await import('./hooks')
  const { QueryClient, QueryObserver } = await import('@tanstack/react-query')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let n = 0
  const fn = () => new Promise<number>((res) => setTimeout(() => res(++n), 20))
  const stop = new QueryObserver(qc, { queryKey: ['k'], queryFn: fn }).subscribe(() => {})
  await new Promise((r) => setTimeout(r, 40))
  void qc.invalidateQueries({ queryKey: ['k'] })
  const p = fetchSettled(qc, ['k'], fn)
  await new Promise((r) => setTimeout(r, 2))
  void qc.invalidateQueries({ queryKey: ['k'] }) // cancels the fetch `p` joined
  await expect(p).resolves.toBeGreaterThan(1)
  stop()
})
