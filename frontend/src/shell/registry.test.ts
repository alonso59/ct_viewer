// @vitest-environment jsdom
// UI-26: on a view-only link, contributions that need write routes are hidden.
import '../i18n'
import { bootstrap } from '../app/bootstrap'
import { registry } from './registry'

test('read-only mode hides every contribution marked `writes`', () => {
  bootstrap()
  registry.setReadOnly(true)
  try {
    const cmds = [...registry.commands.values()].filter((c) => registry.allowed(c)).map((c) => c.id)
    for (const id of ['curation.accept', 'curation.queue', 'radiomics.new', 'tasks.convertDicom', 'project.settings', 'import.open', 'project.exportBundle'])
      expect(cmds).not.toContain(id)
    expect(cmds).toEqual(expect.arrayContaining(['workbench.quickOpen', 'viewer.reset', 'explorer.nextCase']))
    const views = registry.views.filter((v) => registry.allowed(v)).map((v) => v.id)
    expect(views).toEqual(expect.arrayContaining(['project', 'search', 'image', 'history']))
    for (const id of ['curation', 'tasks', 'radiomics', 'variables', 'labels', 'library']) expect(views).not.toContain(id)
    expect(registry.inspectorSections.filter((s) => registry.allowed(s)).map((s) => s.id)).not.toContain('curation.form')
    expect(registry.allowed(registry.getEditor('settings') ?? {})).toBe(false)
  } finally {
    registry.setReadOnly(false)
  }
})

// AUD-A1-06 (UI-02, UI-05): every activity-bar view, panel tab and task is reachable from the palette
test('every view, panel tab and task has a palette command', async () => {
  bootstrap()
  const { useLayout } = await import('../state')
  for (const v of registry.views) {
    const c = registry.commands.get(`view.show.${v.id}`)
    expect(c, v.id).toBeDefined()
    c?.run()
    expect(useLayout.getState().activeView).toBe(v.id)
  }
  for (const p of registry.panelTabs) expect(registry.commands.get(`panel.show.${p.id}`), p.id).toBeDefined()
  const { api } = await import('../api')
  const { syncTaskCommands, taskCommandId } = await import('../features/tasks')
  const list = await api.listTasks()
  syncTaskCommands(list.tasks)
  const visible = list.tasks.filter((x) => !x.manifest.test_only || x.runner_online)
  expect(visible.length).toBeGreaterThan(0)
  for (const x of visible) {
    const c = registry.commands.get(taskCommandId(x.manifest.id))
    expect(c, x.manifest.id).toBeDefined()
    expect(c?.category).toBe('cat.tasks')
  }
  // A task that leaves the list loses its command
  syncTaskCommands(list.tasks.slice(1))
  expect(registry.commands.has(taskCommandId(list.tasks[0]?.manifest.id ?? ''))).toBe(false)
  syncTaskCommands(list.tasks)
})

// AUD-A1-09: menus come from categories; none is named after a plugin
test('every menu command has a category with a menu', async () => {
  bootstrap()
  const { MENUS, menuOf, menuSections } = await import('./menus')
  expect(MENUS.map((m) => m.id)).toEqual(['file', 'edit', 'view', 'go', 'tasks', 'help'])
  const orphans = [...registry.commands.values()].filter((c) => c.menu !== false && !menuOf(c.category)).map((c) => c.id)
  expect(orphans).toEqual([])
  const ids = (m: Parameters<typeof menuSections>[0], scope: Parameters<typeof menuSections>[1]) => menuSections(m, scope).flatMap((s) => s.commands.map((c) => c.id))
  expect(ids('go', 'project')).toEqual(expect.arrayContaining(['explorer.nextCase', 'explorer.prevCase', 'explorer.nextUnreviewed', 'explorer.nextProblem']))
  expect(ids('help', 'project')).toEqual(expect.arrayContaining(['help.keyboard', 'help.about']))
  expect(ids('tasks', 'project')).toEqual(expect.arrayContaining(['radiomics.new', 'tasks.convertDicom']))
  expect(ids('file', 'project')).toEqual(expect.arrayContaining(['project.archive', 'project.exportBundle', 'open.path']))
  expect(menuSections('view', 'project').filter((s) => s.submenu).map((s) => s.category)).toEqual(['cat.showView', 'cat.showPanel'])
})

// AUD-A1-01: the home and Open mode get their own commands, not the project's
test('route-scoped commands', () => {
  bootstrap()
  const on = (scope: 'home' | 'open' | 'project') => [...registry.commands.values()].filter((c) => registry.available(c, scope)).map((c) => c.id)
  expect(on('home')).toEqual(expect.arrayContaining(['workbench.commandPalette', 'project.new', 'open.path', 'tasks.convertDicom', 'project.importBundle', 'workbench.quickOpenProject', 'help.about', 'help.keyboard']))
  for (const id of ['explorer.nextCase', 'curation.accept', 'view.show.project', 'project.archive']) expect(on('home')).not.toContain(id)
  expect(on('open')).toEqual(expect.arrayContaining(['viewer.fit', 'viewer.reset', 'viewer.tool.window', 'help.about']))
  expect(on('open')).not.toContain('curation.accept')
})
