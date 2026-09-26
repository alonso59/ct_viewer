// VW-19 (AUD-A5-05): the set on screen is chosen per project and falls back to `default_seg` for an
// item without a mask in the chosen set, reporting the set it is missing from.
import { resolveSeg } from './viewerSync'

test('chosen set, fallback to default_seg with a notice, or nothing', () => {
  const both = { imported: {}, thr: {} }
  expect(resolveSeg(both, 'thr', 'imported')).toEqual({ seg: 'thr', missing: null })
  expect(resolveSeg(both, undefined, 'imported')).toEqual({ seg: 'imported', missing: null })
  expect(resolveSeg({ imported: {} }, 'thr', 'imported')).toEqual({ seg: 'imported', missing: 'thr' })
  expect(resolveSeg({ other: {} }, 'thr', 'imported')).toEqual({ seg: null, missing: 'thr' })
  expect(resolveSeg({}, 'thr', 'imported')).toEqual({ seg: null, missing: null })
})
