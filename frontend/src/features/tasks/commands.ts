// AUD-A1-06: one palette command per task (`Task: Run …`, TSK-01), kept in step with the task
// list (API-42). Radiomics opens its own settings tab, the canonical entry point (AUD-A1-10).
import { openEditor, registry } from '../../shell'
import type { TaskInfo } from '../../api'

export const RADIOMICS_TASK = 'radiomics.pyradiomics'
const PREFIX = 'task.run.'

export const taskCommandId = (taskId: string) => `${PREFIX}${taskId}`

export function openTask(taskId: string) {
  if (taskId === RADIOMICS_TASK) openEditor('radiomics', {})
  else openEditor('task', { taskId })
}

/** The tasks the Tasks view lists get a command; tasks no longer listed lose theirs */
export function syncTaskCommands(tasks: TaskInfo[]) {
  const visible = tasks.filter((x) => !x.manifest.test_only || x.runner_online)
  const ids = new Set(visible.map((x) => taskCommandId(x.manifest.id)))
  for (const id of [...registry.commands.keys()]) if (id.startsWith(PREFIX) && !ids.has(id)) registry.commands.delete(id)
  for (const x of visible)
    registry.command({
      id: taskCommandId(x.manifest.id),
      writes: true,
      title: 'cmd.runTask',
      titleArgs: { task: x.manifest.title },
      category: 'cat.tasks',
      keywords: [x.manifest.id],
      menuGroup: 5,
      run: () => openTask(x.manifest.id),
    })
}
