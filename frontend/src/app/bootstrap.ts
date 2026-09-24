// One-time registration of all contributions (UI-02). Order = activity bar / panel order is by `order`.
import { createElement, lazy } from 'react'

import i18n from '../i18n'
import { registerExplorer } from '../features/explorer'
import { registerImport } from '../features/import'
import { registerOpen } from '../features/open'
import { registerTasks } from '../features/tasks'
import { registerJobs } from '../features/jobs'
import { registerLibrary } from '../features/library'
import { registerProjects } from '../features/projects'
import { registerVariables } from '../features/variables'
import { registerViewer } from '../features/viewer'
import { activatePlugins, FIRST_PARTY } from '../plugins'
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
import { SettingsView } from './Settings'
import { LiveStatus, ProjectStatus, ReviewerStatus } from './StatusItems'

// The design reference tab and its strings load on first open (NFR-07)
const Design = lazy(() => Promise.all([import('./DesignReference'), import('../i18n/lazy')]).then(([m]) => ({ default: m.DesignReference })))
const DesignReference = () => createElement(Design)

let done = false

export function bootstrap() {
  if (done) return
  done = true
  registerProjects()
  registerImport()
  registerOpen()
  registerTasks()
  registerExplorer()
  registerViewer()
  activatePlugins(FIRST_PARTY) // PLG-04: every shipped plugin, enabled by default
  registerVariables()
  registerJobs()
  registerLibrary()

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
  // UI-24: back to the workspace home; the page change releases every loaded volume (VW-14)
  cmd({ id: 'project.close', title: 'cmd.closeProject', category: 'cat.project', menu: 'file', menuGroup: 9, enabled: () => useWorkbench.getState().pid !== null, run: () => location.assign('/') })
  cmd({ id: 'workbench.settings', title: 'view.settings', category: 'cat.view', keybinding: 'mod+,', menu: 'file', menuGroup: 8, run: () => useLayout.getState().showView('settings') })
  cmd({ id: 'workbench.reviewer', writes: true, title: 'cmd.changeReviewer', category: 'cat.curation', menu: 'edit', menuGroup: 1, run: () => void changeReviewer() })
  cmd({
    id: 'workbench.toggleTheme',
    title: 'cmd.toggleTheme',
    category: 'cat.view',
    menu: 'view',
    menuGroup: 5,
    run: () => useSettings.getState().set({ theme: useSettings.getState().theme === 'light' ? 'dark' : 'light' }),
  })
  for (const [id, view, key] of [['project', 'project', 'mod+shift+e'], ['search', 'search', 'mod+shift+f'], ['curation', 'curation', ''], ['radiomics', 'radiomics', ''], ['variables', 'variables', ''], ['library', 'library', '']] as const)
    cmd({ id: `view.show.${id}`, title: `view.${view}`, category: 'cat.showView', keybinding: key || undefined, menu: 'view', menuGroup: 6, writes: !['project', 'search'].includes(id), run: () => useLayout.getState().set({ activeView: view, sidebarVisible: true }) })
  for (const tab of ['measurements', 'problems', 'history', 'output', 'jobs'])
    cmd({ id: `panel.show.${tab}`, title: `panel.${tab}`, category: 'cat.showPanel', run: () => useLayout.getState().showPanelTab(tab) })
}
