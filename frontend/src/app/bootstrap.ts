// One-time registration of all contributions (UI-02). Order = activity bar / panel order is by `order`.
import { createElement, lazy, Suspense } from 'react'

import i18n from '../i18n'
import { registerExplorer } from '../features/explorer'
import { registerImport } from '../features/import'
import { registerOpen } from '../features/open'
import { registerPhase } from '../features/phase'
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
import { useHelp } from './help'
import { SettingsView } from './Settings'
import { LiveStatus, ProjectStatus, ReviewerStatus } from './StatusItems'

// The design reference tab and its strings load on first open (NFR-07)
const Design = lazy(() => Promise.all([import('./DesignReference'), import('../i18n/lazy')]).then(([m]) => ({ default: m.DesignReference })))
const DesignReference = () => createElement(Design)

// Help › About / Keyboard shortcuts load with their strings on first open (NFR-07)
const Help = lazy(() => Promise.all([import('./HelpDialogs'), import('../i18n/lazy')]).then(([m]) => m))
function HelpDialogs() {
  const open = useHelp((s) => s.open)
  return open ? createElement(Suspense, { fallback: null }, createElement(Help)) : null
}

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
  registerPhase() // ADR-0026: native, whatever plugins are enabled
  activatePlugins(FIRST_PARTY) // PLG-04: every shipped plugin, enabled by default
  registerVariables()
  registerJobs()
  registerLibrary()

  registry.view({ id: 'settings', title: 'view.settings', icon: codicon('settings-gear'), order: 100, position: 'bottom', component: SettingsView, hideImageSection: true })
  registry.editor({ type: 'design', component: DesignReference, id: () => 'design', title: () => i18n.t('design.title'), icon: () => codicon('symbol-color') })
  registry.status({ id: 'core.project', align: 'left', order: 10, component: ProjectStatus })
  registry.status({ id: 'core.live', align: 'left', order: 20, component: LiveStatus })
  registry.status({ id: 'core.reviewer', align: 'right', order: 90, component: ReviewerStatus })

  registry.overlay({ id: 'help.dialogs', component: HelpDialogs })

  const wb = useWorkbench.getState
  const hasTab = () => wb().dock?.activePanel != null
  const cmd = registry.command.bind(registry)
  const everywhere = ['home', 'open', 'project'] as const
  // AUD-A1-09: the menu follows the category (shell/menus.ts); AUD-A1-01: `scope` = where it is offered
  cmd({ id: 'workbench.commandPalette', title: 'cmd.commandPalette', category: 'cat.view', keybinding: 'mod+shift+p', scope: [...everywhere], menuGroup: 1, run: () => wb().openPalette('commands') })
  cmd({ id: 'workbench.quickOpen', title: 'cmd.quickOpen', category: 'cat.navigate', keybinding: 'mod+p', keywords: ['kw.find', 'kw.case'], menuGroup: 0, run: () => wb().openPalette('quickopen') })
  cmd({ id: 'workbench.quickOpenProject', title: 'cmd.openRecent', category: 'cat.file', keybinding: 'mod+p', scope: ['home', 'open'], keywords: ['kw.project'], menuGroup: 1, run: () => wb().openPalette('quickopen') })
  cmd({ id: 'workbench.toggleSidebar', title: 'cmd.toggleSidebar', category: 'cat.view', keybinding: 'mod+b', menuGroup: 2, run: () => useLayout.getState().toggle('sidebarVisible') })
  cmd({ id: 'workbench.togglePanel', title: 'cmd.togglePanel', category: 'cat.view', keybinding: 'mod+j', menuGroup: 2, run: () => useLayout.getState().toggle('panelVisible') })
  cmd({ id: 'workbench.toggleInspector', title: 'cmd.toggleInspector', category: 'cat.view', keybinding: 'mod+alt+b', menuGroup: 2, run: () => useLayout.getState().toggle('inspectorVisible') })
  // Browsers reserve Ctrl/Cmd+W, so the web app uses Alt+W (Ctrl/Cmd+W returns in Electron, P8)
  cmd({ id: 'workbench.closeTab', title: 'cmd.closeTab', category: 'cat.file', keybinding: 'alt+w', menuGroup: 9, enabled: hasTab, run: closeActiveEditor })
  cmd({ id: 'workbench.closeOthers', title: 'cmd.closeOthers', category: 'cat.file', menuGroup: 9, enabled: hasTab, run: closeOtherEditors })
  cmd({ id: 'workbench.split', title: 'cmd.split', category: 'cat.view', keybinding: 'mod+\\', menuGroup: 4, enabled: hasTab, run: splitActiveEditor })
  cmd({ id: 'workbench.welcome', title: 'cmd.welcome', category: 'cat.help', menuGroup: 1, run: () => openEditor('welcome', {}) })
  cmd({ id: 'help.keyboard', title: 'cmd.keyboardShortcuts', category: 'cat.help', scope: [...everywhere], keywords: ['kw.keys', 'kw.keybindings'], menuGroup: 2, run: () => useHelp.getState().show('keys') })
  cmd({ id: 'workbench.design', title: 'design.open', category: 'cat.help', menuGroup: 3, run: () => openEditor('design', {}) })
  // AUD-A4-05 (NFR-16): About with the version and "Research use only"
  cmd({ id: 'help.about', title: 'cmd.about', category: 'cat.help', scope: [...everywhere], keywords: ['kw.version', 'kw.license'], menuGroup: 4, run: () => useHelp.getState().show('about') })
  cmd({ id: 'workbench.home', title: 'projects.home', category: 'cat.file', scope: ['open', 'project'], menuGroup: 1, run: () => location.assign('/') })
  // UI-24: back to the workspace home; the page change releases every loaded volume (VW-14)
  cmd({ id: 'project.close', title: 'cmd.closeProject', category: 'cat.file', menuGroup: 9, enabled: () => useWorkbench.getState().pid !== null, run: () => location.assign('/') })
  cmd({ id: 'workbench.settings', title: 'view.settings', category: 'cat.file', keybinding: 'mod+,', keywords: ['kw.preferences'], menuGroup: 8, run: () => useLayout.getState().showView('settings') })
  cmd({ id: 'workbench.reviewer', writes: true, title: 'cmd.changeReviewer', category: 'cat.edit', menuGroup: 9, run: () => void changeReviewer() })
  cmd({
    id: 'workbench.toggleTheme',
    title: 'cmd.toggleTheme',
    category: 'cat.view',
    scope: [...everywhere],
    menuGroup: 5,
    run: () => useSettings.getState().set({ theme: useSettings.getState().theme === 'light' ? 'dark' : 'light' }),
  })
  // AUD-A1-06: every activity-bar view and panel tab has a command (registry test)
  const viewKeys: Record<string, string> = { project: 'mod+shift+e', search: 'mod+shift+f' }
  for (const v of registry.views)
    cmd({ id: `view.show.${v.id}`, title: v.title, category: 'cat.showView', keybinding: viewKeys[v.id], writes: v.writes, run: () => useLayout.getState().set({ activeView: v.id, sidebarVisible: true }) })
  for (const p of registry.panelTabs)
    cmd({ id: `panel.show.${p.id}`, title: p.title, category: 'cat.showPanel', run: () => useLayout.getState().showPanelTab(p.id) })
}
