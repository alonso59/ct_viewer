// @vitest-environment jsdom
// UI-03 / NFR-07 (FB8, AUD-A0-01): the editor area loads lazily; a tab asked for before it is ready
// opens once it is, and a dock disposed at once (StrictMode) hands the request back.
import type { DockviewApi } from 'dockview-react'
import { expect, test, vi } from 'vitest'

import { codicon } from '../theme'
import { registry } from './registry'
import { flushPendingOpen, openEditor, requeueOpen, useWorkbench } from './workbenchStore'

registry.editor({ type: 'probe', component: () => null, id: (p: { n?: number }) => `probe-${p.n ?? 0}`, title: () => 'Probe', icon: () => codicon('file') })

const fakeDock = () => {
  const addPanel = vi.fn()
  return { addPanel, dock: { getPanel: () => undefined, panels: [], activePanel: undefined, addPanel } as unknown as DockviewApi }
}

test('an open before the dock is ready waits for it; the last one wins; another project drops it', () => {
  useWorkbench.setState({ pid: 'p1', dock: null })
  openEditor('probe', { n: 1 })
  openEditor('probe', { n: 2 })
  const { addPanel, dock } = fakeDock()
  useWorkbench.setState({ dock })
  const args = flushPendingOpen('p1')
  expect(addPanel).toHaveBeenCalledTimes(1)
  expect(addPanel.mock.calls[0]?.[0]).toMatchObject({ id: 'probe-2', params: { type: 'probe', n: 2 } })
  expect(flushPendingOpen('p1')).toBeNull() // consumed
  // StrictMode: the first dock is disposed at once and hands the request back to the second
  requeueOpen('p1', args!)
  useWorkbench.setState({ dock: null })
  expect(flushPendingOpen('p2')).toBeNull() // not for another project
  requeueOpen('p1', args!)
  const second = fakeDock()
  useWorkbench.setState({ dock: second.dock })
  flushPendingOpen('p1')
  expect(second.addPanel).toHaveBeenCalledTimes(1)
  useWorkbench.setState({ pid: null, dock: null })
})
