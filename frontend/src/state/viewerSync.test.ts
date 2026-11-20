// VW-19 (AUD-A5-05): the set on screen is chosen per project and falls back to `default_seg` for an
// item without a mask in the chosen set, reporting the set it is missing from.
import { resolveSeg, segChoiceFor, useViewerSync } from './viewerSync'

test('chosen set, fallback to default_seg with a notice, or nothing', () => {
  const both = { imported: {}, thr: {} }
  expect(resolveSeg(both, 'thr', 'imported')).toEqual({ seg: 'thr', missing: null })
  expect(resolveSeg(both, undefined, 'imported')).toEqual({ seg: 'imported', missing: null })
  expect(resolveSeg({ imported: {} }, 'thr', 'imported')).toEqual({ seg: 'imported', missing: 'thr' })
  expect(resolveSeg({ other: {} }, 'thr', 'imported')).toEqual({ seg: null, missing: 'thr' })
  expect(resolveSeg({}, 'thr', 'imported')).toEqual({ seg: null, missing: null })
})

test('VW-19: a legacy VOI selection does not replace the set for complete scans', () => {
  const pid = 'project'
  const choices = { [pid]: 'imported' }
  expect(resolveSeg({ ensemble: {} }, segChoiceFor(choices, pid, 'complete'), 'ensemble', 'complete')).toEqual({ seg: 'ensemble', missing: null })
  expect(resolveSeg({ imported: {} }, segChoiceFor(choices, pid, 'voi'), 'ensemble', 'voi')).toEqual({ seg: 'imported', missing: null })
  expect(segChoiceFor(choices, pid, 'complete', true)).toBe('imported')
  expect(segChoiceFor({ [pid]: 'model' }, pid, 'complete')).toBe('model')
})

test('VW-19: a set chosen for the active scope leaves the other scope and project alone', () => {
  useViewerSync.setState({ segChoice: {}, activeItemScope: 'voi' })
  const store = useViewerSync.getState()
  store.chooseSeg('one', 'model', 'complete')
  store.chooseSeg('one', 'imported')
  const choices = useViewerSync.getState().segChoice
  expect(segChoiceFor(choices, 'one', 'complete')).toBe('model')
  expect(segChoiceFor(choices, 'one', 'voi')).toBe('imported')
  expect(segChoiceFor(choices, 'two', 'complete')).toBeUndefined()
  expect(resolveSeg({ ensemble: {} }, 'model', 'ensemble')).toEqual({ seg: 'ensemble', missing: 'model' })
  useViewerSync.setState({ segChoice: {}, activeItemScope: 'complete' })
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
