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
