// @vitest-environment jsdom
// UI-13: collapsing an inspector section preserves its unfinished form and project layout.
import { fireEvent, render, screen } from '@testing-library/react'

import '../i18n'
import { useLayout } from '../state'
import { Inspector } from './Inspector'
import { registry } from './registry'

test('section headers collapse independently without unmounting forms', () => {
  const previous = [...registry.inspectorSections]
  registry.inspectorSections.splice(0)
  registry.inspector({ id: 'test.layers', title: 'inspector.layers', order: 1, component: () => <input aria-label="Draft" defaultValue="unfinished" /> })
  registry.inspector({ id: 'test.window', title: 'inspector.window', order: 2, component: () => <p>Window controls</p> })
  useLayout.getState().load('inspector-sections')
  try {
    render(<Inspector />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Draft' }), { target: { value: 'keep this edit' } })
    const layers = screen.getByRole('button', { name: 'Layers' })
    fireEvent.click(layers)
    expect(layers).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByLabelText('Draft')).not.toBeVisible()
    expect(screen.getByText('Window controls')).toBeVisible()
    fireEvent.click(layers)
    expect(screen.getByRole('textbox', { name: 'Draft' })).toHaveValue('keep this edit')
  } finally {
    registry.inspectorSections.splice(0, registry.inspectorSections.length, ...previous)
  }
})
