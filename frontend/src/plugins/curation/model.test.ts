import type { CurationStateRow } from '../../api'
import { decisionsFor, phaseOptions, statusOf, targetsFor } from './model'

const row = (p: Partial<CurationStateRow>): CurationStateRow => ({
  item_id: 'c1.01.complete.-', case_id: 'c1', target: 'seg', status: 'accepted', priority: 'medium', comment: '',
  reviewer: 'A', at: '2026-09-24T10:00:00Z', event_id: 'e', add_to_queue: false, proposed_phase: null, proposed_side: null, ...p,
})

describe('curation model', () => {
  test('targets follow the label map (PRJ-07) and add voi_mask only for VOI items', () => {
    const labels = [{ value: 1, name: 'kidney' }, { value: 2, name: 'tumor' }]
    expect(targetsFor({ scope: 'complete' }, labels).map((o) => o.value)).toEqual(['seg', 'label:1', 'label:2', 'phase', 'side', 'case'])
    expect(targetsFor({ scope: 'voi' }, []).map((o) => o.value)).toContain('voi_mask')
  })

  test('decisions: item targets of the active item plus the case target, newest first', () => {
    const rows = [
      row({ target: 'seg', at: '2026-09-24T10:00:00Z' }),
      row({ item_id: 'c1.02.complete.-', target: 'seg' }),
      row({ item_id: null, target: 'case', status: 'rejected', at: '2026-09-24T11:00:00Z' }),
      row({ item_id: null, case_id: 'c2', target: 'case' }),
    ]
    const d = decisionsFor(rows, 'c1.01.complete.-', 'c1')
    expect(d.map((r) => `${r.item_id ?? 'case'}|${r.target}`)).toEqual(['case|case', 'c1.01.complete.-|seg'])
    expect(decisionsFor(rows, null, null)).toEqual([])
  })

  test('status of one (item, target); case target ignores the item', () => {
    const rows = [row({ target: 'label:2', status: 'needs_minor_correction' }), row({ item_id: null, target: 'case', status: 'rejected' })]
    expect(statusOf(rows, 'c1.01.complete.-', 'c1', 'label:2')).toBe('needs_minor_correction')
    expect(statusOf(rows, 'c1.01.complete.-', 'c1', 'seg')).toBe('not_reviewed')
    expect(statusOf(rows, 'c1.01.complete.-', 'c1', 'case')).toBe('rejected')
  })

  test('phase options fall back to the default vocabulary', () => {
    expect(phaseOptions(['NC', 'ART'])).toEqual(['NC', 'ART'])
    expect(phaseOptions([])).toContain('NP')
  })
})
