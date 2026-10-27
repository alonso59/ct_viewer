import { createElement, lazy, Suspense, useEffect, useRef } from 'react'

import { useTaskRuns, useTasks } from '../../api'
import i18n from '../../i18n'
import { registry, toast, useWorkbench } from '../../shell'
import { codicon } from '../../theme'
import { openTask, syncTaskCommands } from './commands'
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
  registry.view({ id: 'tasks', writes: true, title: 'view.tasks', icon: codicon('run-all'), order: 55, component: LazyView, hideImageSection: true })
  registry.editor<TaskParams>({
    type: 'task',
    writes: true,
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

export { syncTaskCommands, taskCommandId } from './commands'

/** Mount once per writable project: keeps the `Task: Run …` commands in step with the task list */
export function TaskCommands() {
  const tasks = useTasks().data?.tasks
  const pid = useWorkbench((state) => state.pid) ?? ''
  const runs = useTaskRuns(pid).data
  const previous = useRef<{ pid: string; runs: Map<string, string> } | null>(null)
  useEffect(() => {
    if (tasks) syncTaskCommands(tasks)
  }, [tasks])
  useEffect(() => {
    if (!runs) return
    for (const run of runs) {
      const stamp = `${run.job_id}:${run.status}:${run.error}`
      const before = previous.current?.pid === pid ? previous.current.runs.get(run.run_id) : undefined
      if (previous.current?.pid === pid && before !== stamp && run.error && ['failed', 'completed_with_errors'].includes(run.status)) {
        toast({ message: i18n.t('jobs.taskFailedDetail', { name: run.name, error: run.error }), tone: 'error', action: { label: i18n.t('jobs.showTask'), run: () => openTask(run.task.id) } })
      }
    }
    previous.current = { pid, runs: new Map(runs.map((run) => [run.run_id, `${run.job_id}:${run.status}:${run.error}`])) }
  }, [pid, runs])
  return null
}
