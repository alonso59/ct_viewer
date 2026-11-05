import i18n from '../../i18n'
import { openEditor, registry, useWorkbench } from '../../shell'
import { codicon } from '../../theme'
import { createElement, lazy, Suspense } from 'react'
import { useCohort } from './store'

// The cohort view and editor load with their strings on first use
const withStrings = <T,>(mod: () => Promise<T>) => Promise.all([mod(), import('../../i18n/lazy')]).then(([m]) => m as T)
const CohortView = lazy(() => withStrings(() => import('./CohortView')).then((m) => ({ default: m.CohortView })))
const CohortEditor = lazy(() => withStrings(() => import('./CohortEditor')).then((m) => ({ default: m.CohortEditor })))
const CohortViewSuspended = () => createElement(Suspense, { fallback: null }, createElement(CohortView))

export function registerCohort() {
  // Opening a project shows its own open group and pins
  useWorkbench.subscribe((s, prev) => {
    if (s.pid && s.pid !== prev.pid) useCohort.getState().openProject(s.pid)
  })
  registry.view({
    id: 'cohort',
    title: 'view.cohort',
    icon: codicon('table'),
    order: 15,
    component: CohortViewSuspended,
    hideImageSection: true,
  })
  registry.editor({
    type: 'cohort',
    component: CohortEditor,
    id: () => 'cohort',
    title: () => i18n.t('view.cohort'),
    icon: () => codicon('table'),
    path: (pid) => `/p/${pid}/cohort`,
    match: (path) => (path === '/cohort' ? {} : null),
  })
  registry.command({
    id: 'cohort.open',
    title: 'cohort.open',
    category: 'cat.navigate',
    menuGroup: 3,
    enabled: () => useWorkbench.getState().pid !== null,
    run: () => openEditor('cohort', {}),
  })
  // An entry point names the case to reveal in the grid
  registry.command({
    id: 'cohort.showCase',
    title: 'cohort.showCase',
    category: 'cat.navigate',
    menu: false,
    enabled: () => useWorkbench.getState().pid !== null,
    run: (caseId) => {
      if (caseId) useCohort.getState().focus(caseId)
      openEditor('cohort', {})
    },
  })
}
