// @vitest-environment jsdom
// VW-05 / VW-22: the modality next to W/L is always shown; only an assumed one can be changed,
// and then the HU presets follow the choice.
import { fireEvent, render, screen } from '@testing-library/react'

import '../../i18n'
import { ShellProviders, useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { useViewerLocal } from './local'
import { ModalityBadge } from './ModalityBadge'
import type { ViewerHandle } from './model/types'
import { WindowPresets } from './Tools'
import { WindowSection } from './Inspector'

const KEY = 'c|i|ref'
const show = (value: string, assumed = false, component: string | null = null) =>
  useViewerSync.setState({ activeModality: { key: KEY, value, assumed, component }, modalityOverride: {}, customPresets: [] })

beforeEach(() => {
  useWorkbench.setState({ active: { type: 'case' } })
})
afterEach(() => {
  useWorkbench.setState({ active: null })
  useViewerLocal.setState({ active: null })
  useViewerSync.setState({ activeModality: null, customPresets: [] })
})

test('a known modality is a plain badge, with the MR component when it is not magnitude', () => {
  show('CT')
  const { rerender } = render(<ModalityBadge />)
  expect(screen.getByText('CT')).toHaveAttribute('title', 'Modality from the image metadata')
  expect(screen.queryByRole('button')).toBeNull()
  show('MR', false, 'PHASE')
  rerender(<ModalityBadge />)
  expect(screen.getByText('MR · Phase')).toBeInTheDocument()
})

test('an assumed modality is marked and can be changed', () => {
  show('CT', true)
  render(<ShellProviders><ModalityBadge /></ShellProviders>)
  const trigger = screen.getByRole('button', { name: 'Modality: CT (assumed)' })
  expect(trigger).toHaveAttribute('data-tone', 'warn')
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
  fireEvent.click(screen.getByRole('menuitem', { name: 'MR' }))
  expect(useViewerSync.getState().activeModality?.value).toBe('MR')
  expect(useViewerSync.getState().modalityOverride[KEY]).toBe('MR')
})

test('HU presets only for CT; any other image gets the percentile window', () => {
  const defaultWindow = vi.fn((): [number, number] => [800, 300])
  useViewerLocal.setState({ active: { defaultWindow } as unknown as ViewerHandle })
  show('MR')
  render(<ShellProviders><WindowSection /></ShellProviders>)
  expect(screen.queryByRole('button', { name: 'Bone' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Auto (1–99 %)' }))
  expect(defaultWindow).toHaveBeenCalled()
  expect(useViewerSync.getState()).toMatchObject({ ww: 800, wl: 300, preset: 'custom' })
})

test('the Inspector lists the project presets instead of the built-in ones (VW-25)', () => {
  show('CT')
  useViewerSync.setState({ customPresets: [{ name: 'Liver', ww: 150, wl: 90 }] })
  useViewerLocal.setState({ active: {} as ViewerHandle })
  render(<ShellProviders><WindowSection /></ShellProviders>)
  expect(screen.queryByRole('button', { name: 'Bone' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Liver' }))
  expect(useViewerSync.getState()).toMatchObject({ ww: 150, wl: 90 })
})

test('the toolbar W/L menu offers Auto for MR', () => {
  useViewerLocal.setState({ active: { defaultWindow: () => [10, 5] } as unknown as ViewerHandle })
  show('MR')
  render(<ShellProviders><WindowPresets /></ShellProviders>)
  expect(screen.getByText('MR')).toBeInTheDocument() // the badge sits next to W/L
  const menu = screen.getAllByRole('button').find((b) => b.className.includes('toolbar-select'))!
  fireEvent.pointerDown(menu, { button: 0, ctrlKey: false })
  expect(screen.queryByRole('menuitem', { name: /Bone/ })).toBeNull()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Auto (1–99 %)' }))
  expect(useViewerSync.getState()).toMatchObject({ ww: 10, wl: 5 })
})
