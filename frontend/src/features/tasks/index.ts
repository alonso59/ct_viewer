// Tasks (UI-17..20, TSK-*): one generic view and one tab per task. Both load lazily with their
// strings (NFR-07).
import { createElement, lazy, Suspense } from 'react'

import { registry } from '../../shell'
import { codicon } from '../../theme'
import type { TaskParams } from './TaskEditor'

const View = lazy(() => Promise.all([import('./TasksView'), import('../../i18n/lazy')]).then(([m]) => m))
const Editor = lazy(() => Promise.all([import('./TaskEditor'), import('../../i18n/lazy')]).then(([m]) => m))

function LazyView() {
  return createElement(Suspense, { fallback: null }, createElement(View))
}

function LazyEditor(props: { params: TaskParams; panelId: string; active: boolean }) {
  return createElement(Suspense, { fallback: null }, createElement(Editor, props))
}

export function registerTasks() {
  registry.view({ id: 'tasks', title: 'view.tasks', icon: codicon('run-all'), order: 55, component: LazyView, hideImageSection: true })
  registry.editor<TaskParams>({
    type: 'task',
    component: LazyEditor,
    id: (p) => `task:${p.taskId}`,
    title: (p) => p.taskId,
    icon: () => codicon('run-all'),
    path: (pid, p) => `/p/${pid}/tasks/${encodeURIComponent(p.taskId)}`,
    match: (path) => {
      const m = /^\/tasks\/([^/]+)$/.exec(path)
      return m?.[1] ? { taskId: decodeURIComponent(m[1]) } : null
    },
  })
}
