// Projects: workspace home, project switcher, welcome, labels, relink (PRJ-*)
import i18n from '../../i18n'
import { registry } from '../../shell'
import { codicon } from '../../theme'
import { LabelsView } from './LabelsView'
import { WelcomeEditor } from './WelcomeEditor'

export { WorkspaceHome, NewProjectDialog, RelinkDialog } from './WorkspaceHome'
export { useRootsCheck } from './useRootsCheck'
export { ProjectSwitcher } from './ProjectSwitcher'

export function registerProjects() {
  registry.view({ id: 'labels', title: 'view.labels', icon: codicon('tag'), order: 40, component: LabelsView })
  registry.editor({
    type: 'welcome',
    component: WelcomeEditor,
    id: () => 'welcome',
    title: () => i18n.t('welcome.tab'),
    icon: () => codicon('home'),
  })
}
