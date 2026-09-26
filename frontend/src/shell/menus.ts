// Title-bar menus derived from command categories (UI-02, AUD-A1-09): File · Edit · View · Go ·
// Tasks · Help. A command lands in the menu of its category unless it sets `menu: false`.
import { registry, type Command, type MenuId, type RouteScope } from './registry'

/** Menu → the categories it shows, in this order (one section each) */
export const MENUS: { id: MenuId; categories: string[] }[] = [
  { id: 'file', categories: ['cat.file', 'cat.project'] },
  { id: 'edit', categories: ['cat.curation', 'cat.phase', 'cat.edit'] },
  { id: 'view', categories: ['cat.view', 'cat.viewer', 'cat.showView', 'cat.showPanel'] },
  { id: 'go', categories: ['cat.navigate'] },
  { id: 'tasks', categories: ['cat.tasks'] },
  { id: 'help', categories: ['cat.help'] },
]

/** Categories shown as a submenu (they list every view / panel) */
export const SUBMENUS = new Set(['cat.showView', 'cat.showPanel'])

export function menuOf(category: string | undefined): MenuId | null {
  return MENUS.find((m) => category !== undefined && m.categories.includes(category))?.id ?? null
}

export interface MenuSection {
  category: string
  submenu: boolean
  commands: Command[]
}

/** The sections of one menu for the current route: available commands, by category then `menuGroup` */
export function menuSections(menu: MenuId, scope?: RouteScope): MenuSection[] {
  const all = [...registry.commands.values()].filter((c) => c.menu !== false && registry.available(c, scope))
  const def = MENUS.find((m) => m.id === menu)
  return (def?.categories ?? [])
    .map((category) => ({
      category,
      submenu: SUBMENUS.has(category),
      commands: all.filter((c) => c.category === category).sort((a, b) => (a.menuGroup ?? 0) - (b.menuGroup ?? 0)),
    }))
    .filter((s) => s.commands.length > 0)
}
