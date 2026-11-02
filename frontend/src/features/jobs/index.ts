import { registry } from '../../shell'
import { JobsPanel, JobStatus, useJobsBadge } from './JobsPanel'
import { OutputDock, OutputPanel, showOutputChannel } from './Output'

export { logEvent } from './JobsPanel'
export { showOutput } from './Output'

export function registerJobs() {
  registry.panelTab({ id: 'output', title: 'panel.output', order: 40, component: OutputPanel })
  registry.overlay({ id: 'output.dock', component: OutputDock })
  // `arg`: the channel id (a registered output channel); none shows the Activity channel
  registry.command({ id: 'output.show', title: 'cmd.showOutput', category: 'cat.showPanel', scope: ['home', 'open', 'project'], menu: false, run: (arg) => showOutputChannel(arg) })
  registry.panelTab({ id: 'jobs', title: 'panel.jobs', order: 50, component: JobsPanel, useBadge: useJobsBadge })
  registry.status({ id: 'jobs.progress', align: 'left', order: 30, component: JobStatus })
}
