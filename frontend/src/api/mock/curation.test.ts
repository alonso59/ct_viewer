// The mock mirrors the server's CUR-08 case rollup (AUD-A5-15), API-20 `curation_status`
// (AUD-A5-09) and per-set decisions and queue rows (ADR-0015, AUD-A5-06 / A2-16).
import { DEMO_PID, mockServer as api } from './server'

async function settle<T>(p: Promise<T>): Promise<T> {
  const outcome = p.then((value) => ({ value }), (error: unknown) => ({ error }))
  await vi.advanceTimersByTimeAsync(5_000)
  const r = await outcome
  if ('error' in r) throw r.error
  return r.value
}

beforeEach(() => {
  vi.useFakeTimers()
  api.reset()
})
afterEach(() => vi.useRealTimers())

test('one decision of several active items is partially reviewed; the Status filter finds it', async () => {
  const cases = await settle(api.listCases(DEMO_PID))
  const fresh = cases.find((c) => c.review_state === 'not_reviewed' && c.n_items_active > 1)!
  const items = (await settle(api.getCase(DEMO_PID, fresh.case_id))).items.filter((i) => i.status === 'active')
  const base = { case_id: fresh.case_id, priority: 'medium', comment: '', add_to_queue: false } as const
  await settle(api.appendEvent(DEMO_PID, { ...base, item_id: items[0]!.item_id, target: 'side', status: 'accepted' }, 'Dr. T'))
  let c = (await settle(api.getCase(DEMO_PID, fresh.case_id))).summary
  expect([c.curation_status, c.review_state, c.n_items_reviewed]).toEqual(['partially_reviewed', 'partial', 1])
  const hit = await settle(api.listCases(DEMO_PID, { status: 'partially_reviewed' }))
  expect(hit.map((x) => x.case_id)).toContain(fresh.case_id)
  for (const it of items.slice(1)) await settle(api.appendEvent(DEMO_PID, { ...base, item_id: it.item_id, target: 'side', status: 'accepted' }, 'Dr. T'))
  c = (await settle(api.getCase(DEMO_PID, fresh.case_id))).summary
  expect([c.curation_status, c.review_state]).toEqual(['accepted', 'reviewed'])
})

test('mask decisions are kept per set and the queue names the set', async () => {
  const cases = await settle(api.listCases(DEMO_PID))
  const it = (await settle(api.getCase(DEMO_PID, cases[0]!.case_id))).items.find((i) => i.status === 'active')!
  const base = { item_id: it.item_id, case_id: it.case_id, target: 'seg', priority: 'medium', comment: '', add_to_queue: false } as const
  await settle(api.appendEvent(DEMO_PID, { ...base, status: 'accepted' }, 'Dr. T'))
  await settle(api.appendEvent(DEMO_PID, { ...base, status: 'rejected', seg_id: 'thr' }, 'Dr. T'))
  const rows = (await settle(api.curationState(DEMO_PID))).filter((r) => r.item_id === it.item_id && r.target === 'seg')
  expect(rows.map((r) => [r.seg_id, r.status]).sort()).toEqual([['imported', 'accepted'], ['thr', 'rejected']])
  const q = (await settle(api.queue(DEMO_PID))).find((r) => r.item_id === it.item_id)
  expect(q?.seg_id).toBe('thr')
})
