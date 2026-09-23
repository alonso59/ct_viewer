// Jobs: jobs panel, output log, status bar progress (API-41, BE-06)
import { registry } from '../../shell'
import { JobsPanel, JobStatus, OutputPanel, useJobsBadge } from './JobsPanel'

export { logEvent } from './JobsPanel'

export function registerJobs() {
  registry.panelTab({ id: 'output', title: 'panel.output', order: 40, component: OutputPanel })
  registry.panelTab({ id: 'jobs', title: 'panel.jobs', order: 50, component: JobsPanel, useBadge: useJobsBadge })
  registry.status({ id: 'jobs.progress', align: 'left', order: 30, component: JobStatus })
}
