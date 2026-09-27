// Contribution registry (UI-02). Features register what they add; the shell renders it.
// Titles are i18n keys. Registration happens once at bootstrap, before the first render.
import type { ComponentType } from 'react'

import type { IconSpec } from '../theme'

/** The route scope of a pathname: `/p/…` project, `/open…` Open mode, else the workspace home */
export function routeScope(pathname: string = typeof location === 'undefined' ? '/' : location.pathname): RouteScope {
  if (pathname.startsWith('/p/') || pathname.startsWith('/v/')) return 'project'
  if (pathname === '/open' || pathname.startsWith('/open/')) return 'open'
  return 'home'
}

export interface ViewContribution {
  id: string
  title: string
  icon: IconSpec
  order: number
  position?: 'top' | 'bottom'
  component: ComponentType
  /** Header actions (icon buttons) rendered right of the view title */
  actions?: ComponentType
  /** Hide the QuPath-style Image section under this view */
  hideImageSection?: boolean
  useBadge?: () => number | null
  /** Needs write routes: hidden on a view-only link (UI-26) */
  writes?: boolean
}

export interface EditorProps<P> {
  params: P
  panelId: string
  active: boolean
}

export interface EditorContribution<P extends object = object> {
  type: string
  component: ComponentType<EditorProps<P>>
  /** Stable tab id: opening the same params again focuses the existing tab */
  id: (params: P) => string
  title: (params: P) => string
  icon: (params: P) => IconSpec
  /** URL for the active tab (FE-04); omitted = project root */
  path?: (pid: string, params: P) => string
  /** Parse a URL into params, for deep links */
  match?: (pathname: string, search: URLSearchParams) => P | null
  /** Needs write routes: not opened on a view-only link (UI-26) */
  writes?: boolean
}

export interface PanelTabContribution {
  id: string
  title: string
  order: number
  component: ComponentType
  useBadge?: () => number | null
  /** AUD-A3-01: true when the tab has something for the active item (a case tab opens the panel then) */
  useHasContent?: () => boolean
}

/** Title-bar menus (AUD-A1-09): derived from command categories (`shell/menus.ts`), never named after a plugin */
export type MenuId = 'file' | 'edit' | 'view' | 'go' | 'tasks' | 'help'

/** Where a command is offered (AUD-A1-01): the workspace home, Open mode, or inside a project */
export type RouteScope = 'home' | 'open' | 'project'

export interface Command {
  id: string
  /** i18n key; `titleArgs` fill its placeholders (e.g. a task's own title) */
  title: string
  titleArgs?: Record<string, string>
  /** i18n key; it decides the menu (`shell/menus.ts`) and the palette prefix */
  category?: string
  /** Extra palette search words, e.g. `reject`, `fail` for Rejected (AUD-A1-07) */
  keywords?: string[]
  /** Default chord, e.g. `mod+shift+p`, `alt+down`, `shift+1` (UI-12) */
  keybinding?: string
  /** `viewer`: only while a viewer is shown (a case tab or Open mode) and focus is not in a
   *  text field, menu or dialog (UI_SHELL §Default keybindings, AUD-A2-02) */
  when?: 'viewer'
  /** Routes that offer it (palette, menus, keys); default `['project']` */
  scope?: RouteScope[]
  /** `false`: palette and keys only, not in the title-bar menus */
  menu?: false
  /** Order inside its category's menu section */
  menuGroup?: number
  enabled?: () => boolean
  /** `arg`: from a caller that names what to act on (e.g. the converter's source folder) */
  run: (arg?: string) => void
  /** Changes data: hidden and disabled on a view-only link (UI-26) */
  writes?: boolean
}

export interface ItemContribution {
  id: string
  order: number
  component: ComponentType
}

export interface StatusItemContribution extends ItemContribution {
  align: 'left' | 'right'
}

export interface InspectorSectionContribution extends ItemContribution {
  title: string
  writes?: boolean
}

/** Modal work windows launched by a button (PLG `overlays`, e.g. the converter, UI-25); rendered
 *  on every route, so the component must render nothing until it is opened. */
export interface OverlayContribution {
  id: string
  component: ComponentType
  writes?: boolean
}

/** Quick open (Ctrl/Cmd+P) sources: a component that renders cmdk items for the query */
export interface QuickOpenProvider {
  id: string
  order: number
  /** Routes where it lists entries; default `['project']` */
  scope?: RouteScope[]
  component: ComponentType<{ query: string; close: () => void }>
}

class Registry {
  readonly views: ViewContribution[] = []
  readonly editors = new Map<string, EditorContribution<never>>()
  readonly panelTabs: PanelTabContribution[] = []
  readonly commands = new Map<string, Command>()
  readonly tools: ItemContribution[] = []
  readonly statusItems: StatusItemContribution[] = []
  readonly inspectorSections: InspectorSectionContribution[] = []
  readonly quickOpen: QuickOpenProvider[] = []
  readonly imageSection: ItemContribution[] = []
  readonly overlays: OverlayContribution[] = []
  /** UI-26: set by the workbench of a view-only link; contributions with `writes` are hidden */
  readOnly = false

  setReadOnly(on: boolean) {
    this.readOnly = on
  }

  allowed(c: { writes?: boolean }): boolean {
    return !(this.readOnly && c.writes)
  }

  /** Allowed and offered on the current route (AUD-A1-01) */
  available(c: { writes?: boolean; scope?: RouteScope[] }, scope: RouteScope = routeScope()): boolean {
    return this.allowed(c) && (c.scope ?? ['project']).includes(scope)
  }

  /** Named key contexts (`Command.when`); features register the predicate (UI-02) */
  readonly contexts = new Map<string, () => boolean>()
  context(name: string, test: () => boolean) {
    this.contexts.set(name, test)
  }
  inContext(name: string): boolean {
    return this.contexts.get(name)?.() ?? false
  }

  view(v: ViewContribution) {
    this.views.push(v)
    this.views.sort((a, b) => a.order - b.order)
  }
  editor<P extends object>(e: EditorContribution<P>) {
    this.editors.set(e.type, e as unknown as EditorContribution<never>)
  }
  panelTab(p: PanelTabContribution) {
    this.panelTabs.push(p)
    this.panelTabs.sort((a, b) => a.order - b.order)
  }
  command(c: Command) {
    this.commands.set(c.id, c)
  }
  tool(t: ItemContribution) {
    this.tools.push(t)
    this.tools.sort((a, b) => a.order - b.order)
  }
  status(s: StatusItemContribution) {
    this.statusItems.push(s)
    this.statusItems.sort((a, b) => a.order - b.order)
  }
  inspector(s: InspectorSectionContribution) {
    this.inspectorSections.push(s)
    this.inspectorSections.sort((a, b) => a.order - b.order)
  }
  quickOpenProvider(p: QuickOpenProvider) {
    this.quickOpen.push(p)
    this.quickOpen.sort((a, b) => a.order - b.order)
  }
  overlay(o: OverlayContribution) {
    this.overlays.push(o)
  }
  imageSectionContent(s: ItemContribution) {
    this.imageSection.push(s)
  }
  getEditor<P extends object>(type: string): EditorContribution<P> | undefined {
    return this.editors.get(type) as unknown as EditorContribution<P> | undefined
  }
}

export const registry = new Registry()
export type { Registry }
