// @vitest-environment jsdom
// FE-04 / VW-05: a tab activated during mounting must own its viewer controls.
import { act, render, screen } from '@testing-library/react'
import type { IDockviewPanelProps } from 'dockview-react'
import type { ComponentType } from 'react'
import { MemoryRouter } from 'react-router'

import '../i18n'
import { codicon } from '../theme'
import { EditorArea } from './EditorArea'
import { registry } from './registry'
import type { EditorParams } from './workbenchStore'

const panel = vi.hoisted(() => ({
  isActive: false,
  listeners: new Set<(event: { isActive: boolean }) => void>(),
  onDidActiveChange: vi.fn(),
}))

vi.mock('dockview-react', () => ({
  DockviewReact: ({ components }: { components: { editor: ComponentType<IDockviewPanelProps<EditorParams>> } }) => {
    const Host = components.editor
    return <Host {...({ params: { type: 'activity-test' }, api: { id: 'panel', get isActive() { return panel.isActive }, onDidActiveChange: panel.onDidActiveChange } } as unknown as IDockviewPanelProps<EditorParams>)} />
  },
}))

beforeEach(() => {
  panel.isActive = false
  panel.listeners.clear()
  panel.onDidActiveChange.mockImplementation((listener: (event: { isActive: boolean }) => void) => {
    // dockview activated the panel after render, before this listener was attached.
    panel.isActive = true
    panel.listeners.add(listener)
    return { dispose: () => panel.listeners.delete(listener) }
  })
  registry.editor({
    type: 'activity-test',
    component: ({ active }) => <button disabled={!active}>Viewer control</button>,
    id: () => 'panel', title: () => '', icon: () => codicon('file'),
  })
})

afterEach(() => registry.editors.delete('activity-test'))

test('reads an activation missed between render and event subscription', () => {
  render(<MemoryRouter><EditorArea pid="P" /></MemoryRouter>)
  expect(screen.getByRole('button', { name: 'Viewer control' })).toBeEnabled()
})

test('tracks later activation changes and removes the listener on unmount', () => {
  const view = render(<MemoryRouter><EditorArea pid="P" /></MemoryRouter>)
  act(() => {
    panel.isActive = false
    for (const listener of panel.listeners) listener({ isActive: false })
  })
  expect(screen.getByRole('button', { name: 'Viewer control' })).toBeDisabled()
  view.unmount()
  expect(panel.listeners.size).toBe(0)
})
