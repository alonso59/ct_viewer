import { createElement, lazy, Suspense, useEffect, useRef } from 'react'

import { keys, queryClient, useTaskRuns, useTasks, type TaskList } from '../../api'
import i18n from '../../i18n'
import { notify, registry, useWorkbench } from '../../shell'
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
    // the manifest title; the id until the task list has loaded (the editor renames the tab then)
    title: (p) => queryClient.getQueryData<TaskList>(keys.tasks())?.tasks.find((x) => x.manifest.id === p.taskId)?.manifest.title ?? p.taskId,
    icon: () => codicon('run-all'),
    path: (pid, p) => `/p/${pid}/tasks/${encodeURIComponent(p.taskId)}${p.runId ? `?run=${encodeURIComponent(p.runId)}` : ''}`,
    match: (path, search) => {
      const m = /^\/tasks\/([^/]+)$/.exec(path)
      if (!m?.[1]) return null
      const run = search.get('run')
      return { taskId: decodeURIComponent(m[1]), ...(run ? { runId: run } : {}) }
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
        // the task's own tab, when active, shows the error in the run row
        notify(
          { message: i18n.t('jobs.taskFailedDetail', { name: run.name, error: run.error }), tone: 'error', action: { label: i18n.t('jobs.showTask'), run: () => openTask(run.task.id) } },
          (active) => active.type === 'task' && active.taskId === run.task.id,
        )
      }
    }
    previous.current = { pid, runs: new Map(runs.map((run) => [run.run_id, `${run.job_id}:${run.status}:${run.error}`])) }
  }, [pid, runs])
  return null
}
