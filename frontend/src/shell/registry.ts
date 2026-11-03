// Features register what they add; the shell renders it. Titles are i18n keys. Registration happens
// at bootstrap, before the first render. Every list is keyed by `id`: registering an id again replaces
// the entry, so a re-executed module (Vite HMR, a re-activated plugin) swaps its component.
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
  /** Needs write routes: hidden on a view-only link */
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
  /** URL for the active tab; omitted = project root */
  path?: (pid: string, params: P) => string
  /** Parse a URL into params, for deep links */
  match?: (pathname: string, search: URLSearchParams) => P | null
  /** Needs write routes: not opened on a view-only link */
  writes?: boolean
}

export interface PanelTabContribution {
  id: string
  title: string
  order: number
  component: ComponentType
  useBadge?: () => number | null
  /** True when the tab has something for the active item (a case tab opens the panel then) */
  useHasContent?: () => boolean
  /** Hidden on view-only links (UI-26) */
  writes?: boolean
}

/** Title-bar menus, derived from command categories */
export type MenuId = 'file' | 'edit' | 'view' | 'go' | 'tasks' | 'help'

/** Where a command is offered: the workspace home, Open mode, or inside a project */
export type RouteScope = 'home' | 'open' | 'project'

export interface Command {
  id: string
  /** i18n key; `titleArgs` fill its placeholders (e.g. a task's own title) */
  title: string
  titleArgs?: Record<string, string>
  /** i18n key; it decides the menu and the palette prefix */
  category?: string
  /** Extra palette search words, e.g. `reject`, `fail` for Rejected */
  keywords?: string[]
  /** Default chord, e.g. `mod+shift+p`, `alt+down`, `shift+1` */
  keybinding?: string
  /** `viewer`: only while a viewer is shown (a case tab or Open mode) and focus is not in a
   *  text field, menu or dialog */
  when?: 'viewer'
  /** Routes that offer it (palette, menus, keys); default `['project']` */
  scope?: RouteScope[]
  /** `false`: palette and keys only, not in the title-bar menus */
  menu?: false
  /** Order inside its category's menu section */
  menuGroup?: number
  enabled?: () => boolean
  /** Why it is disabled now (an i18n key); the palette then lists it dimmed with the reason instead of hiding it */
  disabledReason?: () => string | undefined
  /** `arg`: from a caller that names what to act on (e.g. the converter's source folder) */
  run: (arg?: string) => void
  /** Changes data: hidden and disabled on a view-only link */
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

/** Modal work windows launched by a button (a plugin's `overlays`, e.g. the converter); rendered
 *  on every route, so the component must render nothing until it is opened. */
export interface OverlayContribution {
  id: string
  component: ComponentType
  writes?: boolean
}

/** A server log the Output tab can follow. Contributed at run time (e.g. when a conversion is
 *  shown), so the list notifies subscribers; `label` is display text, not an i18n key. */
export interface OutputChannelContribution {
  id: string
  label: string
  kind: 'source-operation' | 'workspace-run' | 'project-run' | 'script-run'
  ref: string
  /** The project of a `project-run` */
  project?: string
}

/** Quick open (Ctrl/Cmd+P) sources: a component that renders cmdk items for the query */
export interface QuickOpenProvider {
  id: string
  order: number
  /** Routes where it lists entries; default `['project']` */
  scope?: RouteScope[]
  component: ComponentType<{ query: string; close: () => void }>
}

/** Replace the entry with the same id (or append), then keep the list ordered by `order` (stable) */
function upsert<T extends { id: string; order?: number }>(list: T[], item: T) {
  const i = list.findIndex((x) => x.id === item.id)
  if (i >= 0) list[i] = item
  else list.push(item)
  list.sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
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
  /** Replaced (never mutated) on change, so it is a stable snapshot for `useSyncExternalStore` */
  outputChannels: readonly OutputChannelContribution[] = []
  private readonly channelListeners = new Set<() => void>()
  /** Set by the workbench of a view-only link; contributions with `writes` are hidden */
  readOnly = false

  setReadOnly(on: boolean) {
    this.readOnly = on
  }

  allowed(c: { writes?: boolean }): boolean {
    return !(this.readOnly && c.writes)
  }

  /** Allowed and offered on the current route */
  available(c: { writes?: boolean; scope?: RouteScope[] }, scope: RouteScope = routeScope()): boolean {
    return this.allowed(c) && (c.scope ?? ['project']).includes(scope)
  }

  /** Named key contexts (`Command.when`); features register the predicate */
  readonly contexts = new Map<string, () => boolean>()
  context(name: string, test: () => boolean) {
    this.contexts.set(name, test)
  }
  inContext(name: string): boolean {
    return this.contexts.get(name)?.() ?? false
  }

  view(v: ViewContribution) {
    upsert(this.views, v)
  }
  editor<P extends object>(e: EditorContribution<P>) {
    this.editors.set(e.type, e as unknown as EditorContribution<never>)
  }
  panelTab(p: PanelTabContribution) {
    upsert(this.panelTabs, p)
  }
  command(c: Command) {
    this.commands.set(c.id, c)
  }
  tool(t: ItemContribution) {
    upsert(this.tools, t)
  }
  status(s: StatusItemContribution) {
    upsert(this.statusItems, s)
  }
  inspector(s: InspectorSectionContribution) {
    upsert(this.inspectorSections, s)
  }
  quickOpenProvider(p: QuickOpenProvider) {
    upsert(this.quickOpen, p)
  }
  /** Overlays keep registration order (no `order` field) */
  overlay(o: OverlayContribution) {
    upsert(this.overlays, o)
  }
  outputChannel(c: OutputChannelContribution) {
    const i = this.outputChannels.findIndex((x) => x.id === c.id)
    this.setChannels(i >= 0 ? this.outputChannels.map((x, j) => (j === i ? c : x)) : [...this.outputChannels, c])
  }
  removeOutputChannel(id: string) {
    this.setChannels(this.outputChannels.filter((c) => c.id !== id))
  }
  subscribeOutputChannels = (listener: () => void) => {
    this.channelListeners.add(listener)
    return () => void this.channelListeners.delete(listener)
  }
  private setChannels(list: readonly OutputChannelContribution[]) {
    this.outputChannels = list
    this.channelListeners.forEach((l) => l())
  }
  imageSectionContent(s: ItemContribution) {
    upsert(this.imageSection, s)
  }
  getEditor<P extends object>(type: string): EditorContribution<P> | undefined {
    return this.editors.get(type) as unknown as EditorContribution<P> | undefined
  }
}

export const registry = new Registry()
export type { Registry }
