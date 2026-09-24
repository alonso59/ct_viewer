// Metadata analyzers plugin (plugins/analyzers, ANZ-*): phase, target and readiness tasks, which
// run from the generic task tab (UI-20); their results are annotation layers.
import { openEditor } from '../../shell'
import type { FrontendPlugin } from '../host'

const openPhase = () => openEditor('task', { taskId: 'analyzer.phase' })

export const plugin: FrontendPlugin = {
  id: 'analyzers',
  activate: ({ registry }) => {
    registry.command({ id: 'analyzers.phase', writes: true, title: 'cmd.runPhaseAnalyzer', category: 'cat.project', run: openPhase })
  },
  open: openPhase,
}
