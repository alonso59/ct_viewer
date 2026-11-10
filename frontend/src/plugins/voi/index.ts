// VOI extractor: the `voi.extract` task gets its own settings, a review step and run results
// inside the common task tab; the Tasks view, menu and palette open it like any task.
import { createElement, lazy, Suspense, type ComponentType } from 'react'

import { openEditor } from '../../shell'
import type { FrontendPlugin } from '../host'

const TASK = 'voi.extract'

/** The piece and its strings load on first render of the task tab */
function lazyPart<P extends object>(load: () => Promise<{ default: ComponentType<P> }>): ComponentType<P> {
  const Part = lazy(() => Promise.all([load(), import('../../i18n/lazy')]).then(([m]) => m))
  return (props: P) => createElement(Suspense, { fallback: null }, createElement(Part, props))
}

export const plugin: FrontendPlugin = {
  id: 'voi',
  activate: ({ registry }) => {
    registry.taskExtension({
      taskId: TASK,
      settings: lazyPart(() => import('./Settings')),
      review: lazyPart(() => import('./Review')),
      results: lazyPart(() => import('./Results')),
    })
  },
  open: () => openEditor('task', { taskId: TASK }),
}
