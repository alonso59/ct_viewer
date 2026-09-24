// VW-25: project display settings reach the viewer store; Open mode resets to the defaults.
import type { Project } from '../../api'
import { useViewerSync } from '../../state'
import { applyProjectDisplay, resetDisplay } from './display'

const project = {
  default_modality: 'MR',
  display: { layout: 'three-mpr', wl: { CT: { ww: 350, wl: 40 }, MR: 'percentile' }, use_dicom_window: false, wl_presets: [{ name: 'Liver', ww: 150, wl: 60 }], interpolation: 'nearest', convention: 'neurological' },
} as unknown as Project

test('applies window, presets, interpolation, convention, modality and (once) the layout', () => {
  useViewerSync.setState({ layout: 'four-up' })
  applyProjectDisplay(project, false)
  let s = useViewerSync.getState()
  expect(s.layout).toBe('four-up') // the URL named a layout
  expect(s.ctWindow).toEqual([350, 40])
  expect(s.customPresets).toEqual([{ name: 'Liver', ww: 150, wl: 60 }])
  expect(s.display.interpolation).toBe('nearest')
  expect(s.display.convention).toBe('neurological')
  expect(s.useDicomWindow).toBe(false)
  expect(s.defaultModality).toBe('MR')
  applyProjectDisplay(project, true)
  expect(useViewerSync.getState().layout).toBe('three-mpr')
  useViewerSync.getState().reset()
  s = useViewerSync.getState()
  expect([s.ww, s.wl]).toEqual([350, 40]) // R resets to the project's CT window
  resetDisplay()
  s = useViewerSync.getState()
  expect(s.ctWindow).toEqual([400, 50])
  expect(s.display.convention).toBe('radiological')
  expect(s.customPresets).toEqual([])
})
