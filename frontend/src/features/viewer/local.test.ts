// @vitest-environment jsdom
// VW-27: adopt smooth surfaces without resetting the user's 3D scene or CT visibility.
import { useViewerLocal } from './local'

beforeEach(() => localStorage.clear())

test('existing volume preferences adopt surfaces and retain the rest of the scene', async () => {
  const scene3d = { ...useViewerLocal.getState().scene3d, axes: true, background: 'black' }
  localStorage.setItem('rw.viewer3d', JSON.stringify({ version: 0, state: { surfaces: false, volume3d: false, ctOpacity: 0.35, scene3d } }))
  await useViewerLocal.persist.rehydrate()
  expect(useViewerLocal.getState()).toMatchObject({ surfaces: true, volume3d: false, ctOpacity: 0.35, scene3d })
})

test('an explicit label volume choice survives subsequent reloads', async () => {
  useViewerLocal.setState({ surfaces: false })
  await useViewerLocal.persist.rehydrate()
  expect(useViewerLocal.getState().surfaces).toBe(false)
})
