// UI-06 (AUD-A3-20): the viewer tool group shows only while the active editor is a viewer; the
// active tool is marked with aria-pressed (its --bg-pressed look, AUD-A3-02, is in base.css)
import { render, screen } from '@testing-library/react'

import '../../i18n'
import { ShellProviders, useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { OverlayToggles, ToolGroup } from './Tools'
import { useViewerLocal } from './local'
import type { ViewerHandle } from './model/types'

afterEach(() => {
  useWorkbench.setState({ active: null })
  useViewerLocal.setState({ active: null })
})

test('no viewer tools on a non-viewer editor (dashboard, settings, empty project)', () => {
  useWorkbench.setState({ active: { type: 'run' } })
  const { container } = render(<><ToolGroup /><OverlayToggles /></>)
  expect(container).toBeEmptyDOMElement()
})

test('a case tab shows them (disabled until its viewer is ready), then the active tool pressed', () => {
  useWorkbench.setState({ active: { type: 'case' } })
  useViewerSync.setState({ tool: 'crosshair' })
  const ui = () => <ShellProviders><ToolGroup /></ShellProviders>
  const { rerender } = render(ui())
  expect(screen.getByRole('button', { name: /Crosshair/ })).toBeDisabled()
  useViewerLocal.setState({ active: {} as ViewerHandle })
  rerender(ui())
  expect(screen.getByRole('button', { name: /Crosshair/ })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: /pan/ })).toHaveAttribute('aria-pressed', 'false')
})
