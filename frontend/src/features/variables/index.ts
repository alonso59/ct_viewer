// Study variables (VARIABLES.md): catalog, overrides, derived and external variables (VAR-*)
import { registry, useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { codicon } from '../../theme'
import { useVariablesUi } from './store'
import { createElement, lazy, Suspense } from 'react'

// The view, its dialogs and strings load on first open (NFR-07)
const load = () => Promise.all([import('./VariablesView'), import('../../i18n/lazy')]).then(([m]) => m)
const View = lazy(() => load().then((m) => ({ default: m.VariablesView })))
const Actions = lazy(() => load().then((m) => ({ default: m.VariablesActions })))
const VariablesView = () => createElement(Suspense, { fallback: null }, createElement(View))
const VariablesActions = () => createElement(Suspense, { fallback: null }, createElement(Actions))

export function registerVariables() {
  registry.view({
    id: 'variables',
    writes: true,
    title: 'view.variables',
    icon: codicon('symbol-variable'),
    order: 85,
    component: VariablesView,
    actions: VariablesActions,
    hideImageSection: true,
  })
  const hasProject = () => useWorkbench.getState().pid !== null
  const openDialog = (d: 'derived' | 'external') => {
    useLayout.getState().showView('variables')
    useVariablesUi.getState().openDialog(d)
  }
  registry.command({ id: 'variables.newDerived', writes: true, title: 'variables.newDerived', category: 'cat.edit', menuGroup: 3, enabled: hasProject, run: () => openDialog('derived') })
  registry.command({ id: 'variables.importTable', writes: true, title: 'variables.importTable', category: 'cat.edit', menuGroup: 3, enabled: hasProject, run: () => openDialog('external') })
}
