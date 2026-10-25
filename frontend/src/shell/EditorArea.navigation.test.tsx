// @vitest-environment jsdom
// FE-04 / AUD-A1-02: history and a simultaneous layout refresh must keep the same active case.
import { act, render } from '@testing-library/react'
import type { DockviewApi, DockviewReadyEvent } from 'dockview-react'
import { vi } from 'vitest'

import { codicon } from '../theme'
import { EditorArea } from './EditorArea'
import { registry } from './registry'
import { openEditor, refreshUrl, useWorkbench, type EditorParams } from './workbenchStore'

const route = vi.hoisted(() => ({
  location: { pathname: '/p/P/case/second', search: '' },
  navigate: vi.fn(),
  dock: null as unknown,
}))

vi.mock('react-router', async () => ({
  ...await vi.importActual<typeof import('react-router')>('react-router'),
  useLocation: () => route.location,
  useNavigate: () => route.navigate,
}))

vi.mock('dockview-react', async () => {
  const { createElement, useEffect, useRef } = await import('react')
  return {
    DockviewReact: ({ onReady }: { onReady: (event: DockviewReadyEvent) => void }) => {
      const first = useRef(onReady)
      useEffect(() => first.current({ api: route.dock as DockviewApi }), [])
      return createElement('div')
    },
  }
})

function dock() {
  interface Panel { id: string; params: EditorParams; api: { setActive: () => void; updateParameters: (p: EditorParams) => void } }
  const panels = new Map<string, Panel>()
  let listener: ((event: { panel: Panel }) => void) | undefined
  let activePanel: Panel | undefined
  return {
    get panels() { return [...panels.values()] },
    get activePanel() { return activePanel },
    getPanel: (id: string) => panels.get(id),
    addPanel: ({ id, params }: { id: string; params: EditorParams }) => {
      const panel: Panel = {
        id,
        params,
        api: {
          updateParameters: (next) => { panel.params = next },
          setActive: () => { activePanel = panel; listener?.({ panel }) },
        },
      }
      panels.set(id, panel)
      panel.api.setActive()
      return panel
    },
    onDidActivePanelChange: (callback: typeof listener) => { listener = callback },
    onDidLayoutChange: () => undefined,
    toJSON: () => ({}),
  } as unknown as DockviewApi
}

function registerEditor() {
  registry.editor({
    type: 'history-probe', component: () => null,
    id: (p: { caseId: string }) => `history-${p.caseId}`,
    title: (p) => p.caseId, icon: () => codicon('file'),
    path: (pid, p) => `/p/${pid}/case/${p.caseId}`,
    match: (path) => path.startsWith('/case/') ? { caseId: path.slice('/case/'.length) } : null,
  })
}

test('history reconciliation cannot be overwritten by an active panel captured before that reconciliation', () => {
  localStorage.clear()
  registry.setReadOnly(false)
  registerEditor()
  route.dock = dock()
  route.location = { pathname: '/p/P/case/second', search: '' }
  useWorkbench.setState({ pid: 'P', dock: null, active: null, urlToken: 0 })
  const view = render(<EditorArea pid="P" />)
  try {
    expect(useWorkbench.getState().active?.caseId).toBe('second')
    for (const caseId of ['first', 'second']) {
      route.navigate.mockClear()
      act(() => {
        route.location = { pathname: `/p/P/case/${caseId}`, search: '' }
        refreshUrl()
        view.rerender(<EditorArea pid="P" />)
      })
      expect(useWorkbench.getState().active?.caseId).toBe(caseId)
      expect(route.navigate).not.toHaveBeenCalled()
    }
  } finally {
    view.unmount()
    registry.editors.delete('history-probe')
    useWorkbench.setState({ pid: null, dock: null, active: null })
  }
})

test.each([['first', 'second'], ['second', 'first']])('browser history reconciles %s after an uncommitted transition to %s', (initial, next) => {
  localStorage.clear()
  registry.setReadOnly(false)
  registerEditor()
  const previousUrl = window.location.href
  window.history.replaceState(null, '', `/p/P/case/${initial}`)
  route.dock = dock()
  route.location = { pathname: `/p/P/case/${initial}`, search: '' }
  useWorkbench.setState({ pid: 'P', dock: null, active: null, urlToken: 0 })
  const view = render(<EditorArea pid="P" />)
  try {
    act(() => openEditor('history-probe', { caseId: next }))
    expect(useWorkbench.getState().active?.caseId).toBe(next)
    expect(route.navigate).toHaveBeenCalledWith(`/p/P/case/${next}`, { replace: false })
    // The address changed, but the router's deferred render still describes the initial case.
    // Returning to that entry can leave pathname/search dependencies unchanged.
    route.navigate.mockClear()
    window.history.replaceState(null, '', `/p/another-project/case/${initial}`)
    act(() => window.dispatchEvent(new PopStateEvent('popstate')))
    expect(useWorkbench.getState().active?.caseId).toBe(next)
    window.history.replaceState(null, '', `/p/P/case/${initial}`)
    act(() => window.dispatchEvent(new PopStateEvent('popstate')))
    expect(useWorkbench.getState().active?.caseId).toBe(initial)
    expect(route.navigate).not.toHaveBeenCalled()
  } finally {
    view.unmount()
    window.history.replaceState(null, '', previousUrl)
    registry.editors.delete('history-probe')
    useWorkbench.setState({ pid: null, dock: null, active: null })
  }
})
