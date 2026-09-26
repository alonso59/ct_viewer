import type { CurationStateRow } from '../../api'
import { decisionsFor, statusOf, targetsFor } from './model'

const row = (p: Partial<CurationStateRow>): CurationStateRow => ({
  item_id: 'c1.01.complete.-', case_id: 'c1', target: 'seg', status: 'accepted', priority: 'medium', comment: '',
  reviewer: 'A', at: '2026-09-24T10:00:00Z', event_id: 'e', add_to_queue: false, proposed_side: null, seg_id: 'imported', ...p,
})

describe('curation model', () => {
  test('targets follow the label map (PRJ-07) and add voi_mask only for VOI items', () => {
    const labels = [{ value: 1, name: 'kidney' }, { value: 2, name: 'tumor' }]
    expect(targetsFor({ scope: 'complete' }, labels).map((o) => o.value)).toEqual(['seg', 'label:1', 'label:2', 'side', 'case'])
    expect(targetsFor({ scope: 'voi' }, []).map((o) => o.value)).toContain('voi_mask')
  })

  test('decisions: item targets of the active item plus the case target, newest first', () => {
    const rows = [
      row({ target: 'seg', at: '2026-09-24T10:00:00Z' }),
      row({ item_id: 'c1.02.complete.-', target: 'seg' }),
      row({ item_id: null, target: 'case', status: 'rejected', at: '2026-09-24T11:00:00Z' }),
      row({ item_id: null, case_id: 'c2', target: 'case' }),
    ]
    const d = decisionsFor(rows, 'c1.01.complete.-', 'c1', 'imported')
    expect(d.map((r) => `${r.item_id ?? 'case'}|${r.target}`)).toEqual(['case|case', 'c1.01.complete.-|seg'])
    expect(decisionsFor(rows, null, null, 'imported')).toEqual([])
  })

  test('status of one (item, target); case target ignores the item', () => {
    const rows = [row({ target: 'label:2', status: 'needs_minor_correction' }), row({ item_id: null, target: 'case', status: 'rejected', seg_id: null })]
    expect(statusOf(rows, 'c1.01.complete.-', 'c1', 'label:2', 'imported')).toBe('needs_minor_correction')
    expect(statusOf(rows, 'c1.01.complete.-', 'c1', 'seg', 'imported')).toBe('not_reviewed')
    expect(statusOf(rows, 'c1.01.complete.-', 'c1', 'case', 'imported')).toBe('rejected')
  })

  test('CUR-08 / ADR-0015: mask decisions are per segmentation set (AUD-A5-06)', () => {
    const rows = [
      row({ target: 'seg', seg_id: 'imported', status: 'accepted', at: '2026-09-24T10:00:00Z' }),
      row({ target: 'seg', seg_id: 'thr', status: 'rejected', at: '2026-09-24T11:00:00Z' }),
      row({ target: 'side', seg_id: null, status: 'cannot_assess' }),
    ]
    expect(statusOf(rows, 'c1.01.complete.-', 'c1', 'seg', 'imported')).toBe('accepted')
    expect(statusOf(rows, 'c1.01.complete.-', 'c1', 'seg', 'thr')).toBe('rejected')
    expect(statusOf(rows, 'c1.01.complete.-', 'c1', 'side', 'thr')).toBe('cannot_assess')
    expect(decisionsFor(rows, 'c1.01.complete.-', 'c1', 'thr').map((r) => `${r.target}|${r.status}`)).toEqual(['seg|rejected', 'side|cannot_assess'])
    // an old event without seg_id is the imported set
    expect(statusOf([row({ seg_id: null })], 'c1.01.complete.-', 'c1', 'seg', 'imported')).toBe('accepted')
  })
})
