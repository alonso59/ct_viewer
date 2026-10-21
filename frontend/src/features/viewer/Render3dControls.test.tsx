// @vitest-environment jsdom
// VW-09/27: independently toggle 3D contents; view helpers follow explicit display settings.
import { fireEvent, render, screen } from '@testing-library/react'

import '../../i18n'
import { useViewerSync } from '../../state'
import { useViewerLocal } from './local'
import { DEFAULT_SCENE_3D } from './model/scene3d'
import { Render3dControls } from './Render3dControls'

beforeEach(() => useViewerLocal.setState({ volume3d: true, mask3d: true, ctOpacity: 1, blend: 1, surfaces: false, scene3d: DEFAULT_SCENE_3D }))

test('mask-only leaves 2D overlay and window alone and toggles back to CT + mask', () => {
  useViewerSync.setState({ overlay: true, ww: 350, wl: 40 })
  render(<Render3dControls hasMask canSurface meshState="idle" />)
  fireEvent.click(screen.getByRole('button', { name: '3D view options' }))
  const button = screen.getByRole('button', { name: 'Mask only' })
  fireEvent.click(button)
  expect(button).toHaveAttribute('aria-pressed', 'true')
  expect(useViewerLocal.getState()).toMatchObject({ volume3d: false, mask3d: true })
  expect(useViewerSync.getState()).toMatchObject({ overlay: true, ww: 350, wl: 40 })
  fireEvent.click(button)
  expect(useViewerLocal.getState()).toMatchObject({ volume3d: true, mask3d: true })
})

test('CT and mask visibility, opacity and per-plane guides are independently configurable', () => {
  render(<Render3dControls hasMask canSurface meshState="idle" />)
  fireEvent.click(screen.getByRole('button', { name: '3D view options' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Segmentation mask' }))
  expect(useViewerLocal.getState()).toMatchObject({ volume3d: true, mask3d: false })
  fireEvent.change(screen.getByRole('slider', { name: /CT opacity/ }), { target: { value: '0.35' } })
  expect(useViewerLocal.getState().ctOpacity).toBe(0.35)
  fireEvent.change(screen.getByRole('combobox', { name: 'Axial' }), { target: { value: 'slice' } })
  expect(useViewerLocal.getState().scene3d.planes).toEqual({ axial: 'slice', sagittal: 'off', coronal: 'off' })
  fireEvent.click(screen.getByRole('button', { name: 'Minimal' }))
  expect(useViewerLocal.getState().scene3d).toMatchObject({ bounds: false, axes: false, axisLabels: false, orientationCube: false, annotations: 'none' })
  fireEvent.click(screen.getByRole('button', { name: 'Detailed' }))
  expect(useViewerLocal.getState().scene3d).toMatchObject({ axes: true, planes: { axial: 'outline', sagittal: 'outline', coronal: 'outline' } })
})

test('no segmentation disables mask-only and unavailable surface rendering', () => {
  render(<Render3dControls hasMask={false} canSurface={false} meshState="idle" />)
  fireEvent.click(screen.getByRole('button', { name: '3D view options' }))
  expect(screen.getByRole('button', { name: 'Mask only' })).toBeDisabled()
  expect(screen.getByRole('checkbox', { name: 'Segmentation mask' })).toBeDisabled()
  expect(screen.getByRole('combobox', { name: 'Mask rendering' })).toBeDisabled()
})

test('settings float outside the viewport, move by keyboard, close with Escape and restore focus', () => {
  const { container } = render(<Render3dControls hasMask canSurface meshState="idle" />)
  const trigger = screen.getByRole('button', { name: '3D view options' })
  fireEvent.click(trigger)
  const dialog = screen.getByRole('dialog', { name: '3D view options' })
  expect(container.contains(dialog)).toBe(false)
  const header = dialog.querySelector('.vp-3d-panel-header')!
  const before = parseFloat(dialog.style.left)
  fireEvent.keyDown(header, { key: 'ArrowRight' })
  expect(parseFloat(dialog.style.left)).toBe(before + 20)
  fireEvent.keyDown(header, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  fireEvent.click(trigger)
  expect(screen.getByRole('dialog').style.left).toBe(`${before + 20}px`)
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('the floating panel belongs to the active viewer tab', () => {
  const { rerender } = render(<Render3dControls hasMask canSurface meshState="idle" active />)
  fireEvent.click(screen.getByRole('button', { name: '3D view options' }))
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  rerender(<Render3dControls hasMask canSurface meshState="idle" active={false} />)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
