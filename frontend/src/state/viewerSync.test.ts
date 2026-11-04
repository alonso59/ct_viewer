// VW-19 (AUD-A5-05): the set on screen is chosen per project and falls back to `default_seg` for an
// item without a mask in the chosen set, reporting the set it is missing from.
import { resolveSeg, useViewerSync } from './viewerSync'

test('chosen set, fallback to default_seg with a notice, or nothing', () => {
  const both = { imported: {}, thr: {} }
  expect(resolveSeg(both, 'thr', 'imported')).toEqual({ seg: 'thr', missing: null })
  expect(resolveSeg(both, undefined, 'imported')).toEqual({ seg: 'imported', missing: null })
  expect(resolveSeg({ imported: {} }, 'thr', 'imported')).toEqual({ seg: 'imported', missing: 'thr' })
  expect(resolveSeg({ other: {} }, 'thr', 'imported')).toEqual({ seg: null, missing: 'thr' })
  expect(resolveSeg({}, 'thr', 'imported')).toEqual({ seg: null, missing: null })
})

// VW-05: reset returns a CT to the project's CT window; any other image keeps its window here and
// the viewer applies its percentile window (the store cannot compute it)
test('reset: CT window for CT, the viewer decides for other modalities', () => {
  const s = useViewerSync.getState()
  useViewerSync.setState({ ctWindow: [400, 50], ww: 900, wl: 200, activeModality: { key: 'k', value: 'MR', assumed: false, component: null } })
  const token = s.resetToken
  useViewerSync.getState().reset()
  expect(useViewerSync.getState()).toMatchObject({ ww: 900, wl: 200, resetToken: token + 1 })
  useViewerSync.setState({ activeModality: { key: 'k', value: 'CT', assumed: false, component: null } })
  useViewerSync.getState().reset()
  expect(useViewerSync.getState()).toMatchObject({ ww: 400, wl: 50, preset: 'soft_tissue', resetToken: token + 2 })
  useViewerSync.setState({ activeModality: null })
})
