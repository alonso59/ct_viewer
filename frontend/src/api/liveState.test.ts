// CUR-11/12: an SSE curation event updates the cached state at once (last event wins per target).
import { upsertStateRow } from './hooks'
import type { CurationEvent, CurationStateRow } from './types'

const ev = (id: string, status: CurationEvent['status'], reviewer: string) =>
  ({ event_id: id, item_id: 'i1', case_id: 'c1', target: 'seg', status, priority: 'medium', comment: '', reviewer, at: '2026-09-25T00:00:00Z', add_to_queue: false }) as CurationEvent

test('upsert replaces the row of the same (item, target) and ignores a replayed event', () => {
  const other: CurationStateRow = { ...upsertStateRow([], ev('e0', 'accepted', 'x'))[0]!, target: 'phase', event_id: 'p' }
  let rows = upsertStateRow([other], ev('e1', 'accepted', 'Dr. A'))
  expect(rows.map((r) => [r.target, r.status])).toEqual([['phase', 'accepted'], ['seg', 'accepted']])
  rows = upsertStateRow(rows, ev('e2', 'rejected', 'Dr. B'))
  expect(rows.filter((r) => r.target === 'seg').map((r) => [r.status, r.reviewer])).toEqual([['rejected', 'Dr. B']])
  expect(upsertStateRow(rows, ev('e2', 'rejected', 'Dr. B'))).toBe(rows)
})
