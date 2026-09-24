// Projects: workspace home, project switcher, welcome, labels, relink, bundles, full hashes (PRJ-*)
import i18n from '../../i18n'
import { registry, useWorkbench } from '../../shell'
import { codicon } from '../../theme'
import { computeHashes, exportBundle } from './actions'
import { LabelsView } from './LabelsView'
import { WelcomeEditor } from './WelcomeEditor'

export { WorkspaceHome, NewProjectDialog, RelinkDialog } from './WorkspaceHome'
export { useRootsCheck } from './useRootsCheck'
export { ProjectSwitcher } from './ProjectSwitcher'

/** Runs `fn` on the open project, if any */
const withPid = (fn: (pid: string) => unknown) => () => {
  const pid = useWorkbench.getState().pid
  if (pid) void fn(pid)
}

export function registerProjects() {
  registry.view({ id: 'labels', title: 'view.labels', icon: codicon('tag'), order: 40, component: LabelsView })
  registry.editor({
    type: 'welcome',
    component: WelcomeEditor,
    id: () => 'welcome',
    title: () => i18n.t('welcome.tab'),
    icon: () => codicon('home'),
  })
  registry.command({ id: 'project.exportBundle', title: 'projects.bundle.export', category: 'cat.project', run: withPid(exportBundle) })
  registry.command({ id: 'project.computeHashes', title: 'projects.hash.compute', category: 'cat.project', run: withPid((pid) => computeHashes(pid)) })
  registry.command({ id: 'project.recomputeHashes', title: 'projects.hash.recompute', category: 'cat.project', run: withPid((pid) => computeHashes(pid, true)) })
}
