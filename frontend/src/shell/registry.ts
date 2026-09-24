// Contribution registry (UI-02). Features register what they add; the shell renders it.
// Titles are i18n keys. Registration happens once at bootstrap, before the first render.
import type { ComponentType } from 'react'

import type { IconSpec } from '../theme'

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
}

export type MenuId = 'file' | 'edit' | 'view' | 'project' | 'radiomics' | 'help'

export interface Command {
  id: string
  title: string
  category?: string
  /** Default chord, e.g. `mod+shift+p`, `alt+down`, `shift+1` (UI-12) */
  keybinding?: string
  /** `viewer`: only while the viewer has focus (UI_SHELL §Default keybindings) */
  when?: 'viewer'
  menu?: MenuId
  menuGroup?: number
  enabled?: () => boolean
  run: () => void
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

/** Quick open (Ctrl/Cmd+P) sources: a component that renders cmdk items for the query */
export interface QuickOpenProvider {
  id: string
  order: number
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
  /** UI-26: set by the workbench of a view-only link; contributions with `writes` are hidden */
  readOnly = false

  setReadOnly(on: boolean) {
    this.readOnly = on
  }

  allowed(c: { writes?: boolean }): boolean {
    return !(this.readOnly && c.writes)
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
  imageSectionContent(s: ItemContribution) {
    this.imageSection.push(s)
  }
  getEditor<P extends object>(type: string): EditorContribution<P> | undefined {
    return this.editors.get(type) as unknown as EditorContribution<P> | undefined
  }
}

export const registry = new Registry()
export type { Registry }
