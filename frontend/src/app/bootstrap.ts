// One-time registration of all contributions (UI-02). Order = activity bar / panel order is by `order`.
import i18n from '../i18n'
import { registerCuration } from '../features/curation'
import { registerDashboard } from '../features/dashboard'
import { registerExplorer } from '../features/explorer'
import { registerImport } from '../features/import'
import { registerJobs } from '../features/jobs'
import { registerProjects } from '../features/projects'
import { registerRadiomics } from '../features/radiomics'
import { registerViewer } from '../features/viewer'
import {
  closeActiveEditor,
  closeOtherEditors,
  openEditor,
  registry,
  splitActiveEditor,
  useWorkbench,
} from '../shell'
import { changeReviewer, useLayout, useSettings } from '../state'
import { codicon } from '../theme'
import { DesignReference } from './DesignReference'
import { SettingsView } from './Settings'
import { LiveStatus, ProjectStatus, ReviewerStatus } from './StatusItems'

let done = false

export function bootstrap() {
  if (done) return
  done = true
  registerProjects()
  registerImport()
  registerExplorer()
  registerViewer()
  registerCuration()
  registerRadiomics()
  registerDashboard()
  registerJobs()

  registry.view({ id: 'settings', title: 'view.settings', icon: codicon('settings-gear'), order: 100, position: 'bottom', component: SettingsView, hideImageSection: true })
  registry.editor({ type: 'design', component: DesignReference, id: () => 'design', title: () => i18n.t('design.title'), icon: () => codicon('symbol-color') })
  registry.status({ id: 'core.project', align: 'left', order: 10, component: ProjectStatus })
  registry.status({ id: 'core.live', align: 'left', order: 20, component: LiveStatus })
  registry.status({ id: 'core.reviewer', align: 'right', order: 90, component: ReviewerStatus })

  const wb = useWorkbench.getState
  const hasTab = () => wb().dock?.activePanel != null
  const cmd = registry.command.bind(registry)
  cmd({ id: 'workbench.commandPalette', title: 'cmd.commandPalette', category: 'cat.view', keybinding: 'mod+shift+p', menu: 'view', menuGroup: 1, run: () => wb().openPalette('commands') })
  cmd({ id: 'workbench.quickOpen', title: 'cmd.quickOpen', category: 'cat.navigate', keybinding: 'mod+p', menu: 'view', menuGroup: 1, run: () => wb().openPalette('quickopen') })
  cmd({ id: 'workbench.toggleSidebar', title: 'cmd.toggleSidebar', category: 'cat.view', keybinding: 'mod+b', menu: 'view', menuGroup: 2, run: () => useLayout.getState().toggle('sidebarVisible') })
  cmd({ id: 'workbench.togglePanel', title: 'cmd.togglePanel', category: 'cat.view', keybinding: 'mod+j', menu: 'view', menuGroup: 2, run: () => useLayout.getState().toggle('panelVisible') })
  cmd({ id: 'workbench.toggleInspector', title: 'cmd.toggleInspector', category: 'cat.view', keybinding: 'mod+alt+b', menu: 'view', menuGroup: 2, run: () => useLayout.getState().toggle('inspectorVisible') })
  // Browsers reserve Ctrl/Cmd+W, so the web app uses Alt+W (Ctrl/Cmd+W returns in Electron, P8)
  cmd({ id: 'workbench.closeTab', title: 'cmd.closeTab', category: 'cat.view', keybinding: 'alt+w', menu: 'file', menuGroup: 9, enabled: hasTab, run: closeActiveEditor })
  cmd({ id: 'workbench.closeOthers', title: 'cmd.closeOthers', category: 'cat.view', menu: 'file', menuGroup: 9, enabled: hasTab, run: closeOtherEditors })
  cmd({ id: 'workbench.split', title: 'cmd.split', category: 'cat.view', keybinding: 'mod+\\', menu: 'view', menuGroup: 4, enabled: hasTab, run: splitActiveEditor })
  cmd({ id: 'workbench.welcome', title: 'cmd.welcome', category: 'cat.help', menu: 'help', menuGroup: 1, run: () => openEditor('welcome', {}) })
  cmd({ id: 'workbench.design', title: 'design.open', category: 'cat.help', menu: 'help', menuGroup: 1, run: () => openEditor('design', {}) })
  cmd({ id: 'workbench.home', title: 'projects.home', category: 'cat.project', menu: 'file', menuGroup: 1, run: () => location.assign('/') })
  cmd({ id: 'workbench.settings', title: 'view.settings', category: 'cat.view', keybinding: 'mod+,', menu: 'file', menuGroup: 8, run: () => useLayout.getState().showView('settings') })
  cmd({ id: 'workbench.reviewer', title: 'cmd.changeReviewer', category: 'cat.curation', menu: 'edit', menuGroup: 1, run: () => void changeReviewer() })
  cmd({
    id: 'workbench.toggleTheme',
    title: 'cmd.toggleTheme',
    category: 'cat.view',
    menu: 'view',
    menuGroup: 5,
    run: () => useSettings.getState().set({ theme: useSettings.getState().theme === 'light' ? 'dark' : 'light' }),
  })
  for (const [id, view, key] of [['project', 'project', 'mod+shift+e'], ['search', 'search', 'mod+shift+f'], ['curation', 'curation', ''], ['radiomics', 'radiomics', '']] as const)
    cmd({ id: `view.show.${id}`, title: `view.${view}`, category: 'cat.showView', keybinding: key || undefined, menu: 'view', menuGroup: 6, run: () => useLayout.getState().set({ activeView: view, sidebarVisible: true }) })
  for (const tab of ['measurements', 'problems', 'history', 'output', 'jobs'])
    cmd({ id: `panel.show.${tab}`, title: `panel.${tab}`, category: 'cat.showPanel', run: () => useLayout.getState().showPanelTab(tab) })
}
