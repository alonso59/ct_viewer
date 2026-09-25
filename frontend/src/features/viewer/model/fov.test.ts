// VW-06/26: per-view field of view, linking and fit
import { useViewerLocal } from '../local'
import { FIT, fitFov, fovOf, linkFov, setFov, zoomed, ZOOM_MAX, ZOOM_MIN, type FovMap } from './fov'

describe('field of view (VW-06, VW-26)', () => {
  test('zoom is independent per view by default; the link toggle is opt-in', () => {
    expect(useViewerLocal.getState().linkZoom).toBe(false)
    const m: FovMap = {}
    setFov(m, 'axial', zoomed(fovOf(m, 'axial'), 2), false)
    expect(fovOf(m, 'axial')[3]).toBe(2)
    expect(fovOf(m, 'sagittal')).toEqual(FIT)
    expect(fovOf(m, 'coronal')).toEqual(FIT)
  })

  test('linked zoom writes every 2D view; linking copies the last-used view', () => {
    const m: FovMap = {}
    setFov(m, 'sagittal', [5, 0, -3, 3], false)
    linkFov(m, 'sagittal')
    expect(fovOf(m, 'axial')).toEqual([5, 0, -3, 3])
    expect(fovOf(m, 'coronal')).toEqual([5, 0, -3, 3])
    setFov(m, 'axial', zoomed(fovOf(m, 'axial'), 0.5), true)
    expect([m.axial?.[3], m.sagittal?.[3], m.coronal?.[3]]).toEqual([1.5, 1.5, 1.5])
    // views never share one array
    m.axial![0] = 99
    expect(m.sagittal![0]).toBe(5)
  })

  test('fit restores zoom 100 % and zero pan on one view only, or on all when linked', () => {
    const m: FovMap = { axial: [10, 20, 0, 4], sagittal: [0, 1, 2, 2], coronal: [1, 0, 0, 3] }
    fitFov(m, 'axial', false)
    expect(fovOf(m, 'axial')).toEqual(FIT)
    expect(fovOf(m, 'sagittal')).toEqual([0, 1, 2, 2])
    expect(fovOf(m, 'coronal')).toEqual([1, 0, 0, 3])
    fitFov(m, 'coronal', true)
    for (const p of ['axial', 'sagittal', 'coronal'] as const) expect(fovOf(m, p)).toEqual(FIT)
  })

  test('zoom is clamped', () => {
    expect(zoomed([0, 0, 0, 1], 1000)[3]).toBe(ZOOM_MAX)
    expect(zoomed([0, 0, 0, 1], 0.001)[3]).toBe(ZOOM_MIN)
  })
})
