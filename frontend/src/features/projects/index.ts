// Projects: workspace home, project switcher, welcome, labels, relink, bundles, full hashes
import i18n from '../../i18n'
import { api, keys, queryClient, type Project } from '../../api'
import { openEditor, registry, useWorkbench } from '../../shell'
import { codicon } from '../../theme'
import { computeHashes, exportBundle } from './actions'
import { ArchiveDialog, copyEditLink, copyViewLink, QuickOpenProjects } from './share'
import { useProjectDialogs } from './store'
import { LabelsView } from './LabelsView'
import { LazyProjectSettings } from './settings/LazyProjectSettings'
import type { SettingsParams } from './settings/ProjectSettings'
import { WelcomeEditor } from './WelcomeEditor'

export { WorkspaceHome } from './WorkspaceHome'
export { RelinkDialog } from './RelinkDialog'
export { useRootsCheck } from './useRootsCheck'
export { useProjectDialogs } from './store'
export { ProjectSwitcher } from './ProjectSwitcher'
export { ShareMenu } from './share'

const withPid = (fn: (pid: string) => unknown) => () => {
  const pid = useWorkbench.getState().pid
  if (pid) void fn(pid)
}

export function registerProjects() {
  registry.view({ id: 'labels', writes: true, title: 'view.labels', icon: codicon('tag'), order: 40, component: LabelsView })
  registry.editor({
    type: 'welcome',
    component: WelcomeEditor,
    id: () => 'welcome',
    title: () => i18n.t('welcome.tab'),
    icon: () => codicon('home'),
  })
  registry.editor<SettingsParams>({
    type: 'settings',
    writes: true,
    component: LazyProjectSettings,
    id: () => 'settings',
    title: () => i18n.t('psettings.open'),
    icon: () => codicon('settings'),
    path: (pid) => `/p/${pid}/settings`,
    match: (path) => (path === '/settings' ? {} : null),
  })
  registry.command({ id: 'project.settings', writes: true, title: 'psettings.open', category: 'cat.project', menuGroup: 1, run: () => openEditor('settings', {}) })
  const hasPid = () => useWorkbench.getState().pid !== null
  registry.command({ id: 'project.new', writes: true, title: 'home.newProject', category: 'cat.file', scope: ['home', 'project'], menuGroup: 0, run: () => useProjectDialogs.getState().set({ creating: true }) })
  registry.command({ id: 'project.importBundle', writes: true, title: 'home.importBundle', category: 'cat.file', scope: ['home'], menuGroup: 2, run: () => useProjectDialogs.setState((s) => ({ bundlePick: s.bundlePick + 1 })) })
  registry.command({ id: 'project.copyEditLink', writes: true, title: 'shell.copyEditLink', category: 'cat.project', keywords: ['kw.share', 'kw.link', 'kw.url'], menuGroup: 2, enabled: hasPid, run: () => copyEditLink() })
  registry.command({ id: 'project.copyViewLink', title: 'shell.copyViewLink', category: 'cat.project', keywords: ['kw.share', 'kw.link', 'kw.url', 'kw.readOnly'], menuGroup: 2, enabled: hasPid, run: () => void copyViewLink() })
  registry.overlay({ id: 'projects.archive', writes: true, component: ArchiveDialog })
  registry.command({
    id: 'project.archive',
    writes: true,
    title: 'projects.archiveMenu',
    category: 'cat.project',
    menuGroup: 9,
    enabled: hasPid,
    run: withPid((pid) => useProjectDialogs.getState().set({ archive: { pid, name: queryClient.getQueryData<Project>(keys.project(pid))?.name ?? pid, home: false } })),
  })
  // Also the missing-image card's next step
  registry.command({ id: 'project.relink', writes: true, title: 'projects.relink', category: 'cat.project', menuGroup: 3, enabled: hasPid, run: withPid((pid) => useProjectDialogs.getState().set({ relink: pid })) })
  for (const [fmt, title] of [['csv', 'cmd.exportDatasetCsv'], ['parquet', 'cmd.exportDatasetParquet'], ['jsonl', 'cmd.exportDatasetJsonl']] as const)
    registry.command({
      id: `project.exportDataset.${fmt}`,
      title,
      category: 'cat.file',
      keywords: ['kw.dataset', 'kw.export'],
      menuGroup: 6,
      enabled: hasPid,
      run: withPid((pid) => {
        const a = document.createElement('a')
        a.href = api.datasetTableUrl(pid, fmt)
        a.download = ''
        a.click()
      }),
    })
  registry.quickOpenProvider({ id: 'projects', order: 10, scope: ['home', 'open'], component: QuickOpenProjects })
  registry.command({ id: 'project.exportBundle', writes: true, title: 'projects.bundle.export', category: 'cat.file', menuGroup: 5, run: withPid(exportBundle) })
  registry.command({ id: 'project.computeHashes', writes: true, title: 'projects.hash.compute', category: 'cat.tasks', menuGroup: 4, run: withPid((pid) => computeHashes(pid)) })
  registry.command({ id: 'project.recomputeHashes', writes: true, title: 'projects.hash.recompute', category: 'cat.tasks', menuGroup: 4, run: withPid((pid) => computeHashes(pid, true)) })
}
