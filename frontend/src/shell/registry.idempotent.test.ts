// @vitest-environment jsdom
// AUD-A8-01/02 (UI-02): registration is idempotent. Re-running bootstrap and plugin activation with
// fresh module instances (what Vite HMR does: the feature, plugin and bootstrap modules re-execute
// with their guards reset, the registry singleton does not) leaves every contribution list the same
// size, and the re-executed module's component replaces the old one.
import type { ComponentType } from 'react'

import '../i18n'
import * as registryModule from './registry'

const { registry } = registryModule

type Entry = { id: string; component?: unknown }
const lists = () => ({
  views: registry.views,
  panelTabs: registry.panelTabs,
  tools: registry.tools,
  statusItems: registry.statusItems,
  inspectorSections: registry.inspectorSections,
  quickOpen: registry.quickOpen,
  overlays: registry.overlays,
  imageSection: registry.imageSection,
})
const snapshot = () => Object.fromEntries(Object.entries(lists()).map(([k, l]) => [k, (l as Entry[]).map((e) => ({ id: e.id, component: e.component }))]))

test('every register* call replaces an entry with the same id (then sorts)', () => {
  const A: ComponentType = () => null
  const B: ComponentType = () => null
  const reg = new (registry.constructor as new () => typeof registry)()
  for (const component of [A, B]) {
    reg.view({ id: 't.view', title: 't', icon: { kind: 'codicon', name: 'x' } as never, order: 5, component })
    reg.view({ id: 't.first', title: 't', icon: { kind: 'codicon', name: 'x' } as never, order: 1, component })
    reg.panelTab({ id: 't.panel', title: 't', order: 1, component })
    reg.tool({ id: 't.tool', order: 1, component })
    reg.status({ id: 't.status', align: 'left', order: 1, component })
    reg.inspector({ id: 't.inspector', title: 't', order: 1, component })
    reg.quickOpenProvider({ id: 't.quick', order: 1, component: component as never })
    reg.overlay({ id: 't.overlay', component })
    reg.imageSectionContent({ id: 't.image', order: 1, component })
    reg.command({ id: 't.cmd', title: 't', run: () => undefined })
    reg.editor({ type: 't.editor', component: component as never, id: () => 'x', title: () => 'x', icon: () => ({}) as never })
  }
  expect(reg.views.map((v) => v.id)).toEqual(['t.first', 't.view'])
  for (const l of [reg.views, reg.panelTabs, reg.tools, reg.statusItems, reg.inspectorSections, reg.quickOpen, reg.overlays, reg.imageSection]) {
    expect(l.filter((e) => e.id.startsWith('t.')).every((e) => e.component === B)).toBe(true)
  }
  expect(reg.panelTabs).toHaveLength(1)
  expect(reg.overlays).toHaveLength(1)
  expect(reg.commands.size).toBe(1)
  expect(reg.editors.size).toBe(1)
})

test('re-executed bootstrap, features and plugins (HMR) do not duplicate contributions', async () => {
  const { bootstrap } = await import('../app/bootstrap')
  bootstrap()
  const before = snapshot()
  const nCommands = registry.commands.size
  const nEditors = registry.editors.size
  expect(before.views?.length).toBe(13) // the activity bar of a project (A8 reproduction)

  // HMR: every module except the registry re-executes, so `done` and the plugin host's map reset
  vi.resetModules()
  vi.doMock('./registry', () => registryModule)
  const fresh = await import('../app/bootstrap')
  const plugins = await import('../plugins')
  fresh.bootstrap()
  plugins.activatePlugins(plugins.FIRST_PARTY) // fresh host map: activates every plugin again
  plugins.activatePlugins(plugins.FIRST_PARTY)
  const after = snapshot()

  for (const [k, l] of Object.entries(before)) expect(after[k]?.map((e) => e.id), k).toEqual(l.map((e) => e.id))
  expect(registry.commands.size).toBe(nCommands)
  expect(registry.editors.size).toBe(nEditors)
  // the second (re-executed) component wins
  const oldProject = before.views?.find((v) => v.id === 'project')?.component
  const newProject = after.views?.find((v) => v.id === 'project')?.component
  expect(newProject).toBeDefined()
  expect(newProject).not.toBe(oldProject)
  const { SettingsView } = await import('../app/Settings')
  expect(after.views?.find((v) => v.id === 'settings')?.component).toBe(SettingsView)
  vi.doUnmock('./registry')
})
