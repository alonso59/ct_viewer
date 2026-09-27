// @vitest-environment jsdom
// TST-17 (PLG-03/04): activation registers each plugin's contributions once; Open handlers exist.
import '../i18n'
import { registry } from '../shell/registry'
import { FIRST_PARTY, activatePlugins, isActive, openerOf } from '.'

test('activating the first-party plugins registers their contributions once', () => {
  activatePlugins(FIRST_PARTY)
  activatePlugins(FIRST_PARTY) // idempotent
  for (const p of FIRST_PARTY) expect(isActive(p.id)).toBe(true)
  const views = registry.views.map((v) => v.id)
  expect(views.filter((v) => v === 'curation')).toHaveLength(1)
  expect(views).toEqual(expect.arrayContaining(['curation', 'history', 'radiomics', 'dashboards']))
  expect(registry.getEditor('queue')).toBeDefined()
  expect(registry.getEditor('radiomics')).toBeDefined()
  expect(registry.getEditor('run')).toBeDefined()
  expect(registry.panelTabs.map((p) => p.id)).toEqual(expect.arrayContaining(['measurements', 'history']))
  expect(registry.commands.has('tasks.convertDicom')).toBe(true)
  expect(registry.commands.has('analyzers.phase')).toBe(true)
  for (const id of ['dicom', 'analyzers', 'curation', 'labeling', 'radiomics', 'dashboard', 'ccrcc', 'generic-ct']) expect(openerOf(id)).toBeTypeOf('function')
  expect(openerOf('nnunet')).toBeNull() // pending: no UI (PLG-09)
})
