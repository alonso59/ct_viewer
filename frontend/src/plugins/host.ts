// Plugin host (PLG-01/03/04, ADR-0018). Every first-party plugin exports a small `FrontendPlugin`;
// activation registers its contributions in the shell registry (UI-02). All shipped plugins are
// enabled by default, so bootstrap activates every one; heavy UI stays in each plugin's lazy chunks.
import { registry, type Registry } from '../shell/registry'
import { useLayout } from '../state'

export interface PluginContext {
  registry: Registry
  /** Show an activity-bar view (never toggles it closed) */
  revealView: (viewId: string) => void
}

export interface FrontendPlugin {
  /** The id of `plugins/<id>/plugin.json` */
  id: string
  activate: (ctx: PluginContext) => void
  /** The Library's Open action: the plugin's main surface (PLG-05) */
  open?: () => void
}

const active = new Map<string, FrontendPlugin>()

export const revealView = (viewId: string) => useLayout.getState().set({ activeView: viewId, sidebarVisible: true })

const context: PluginContext = { registry, revealView }

/** Activates each plugin once (PLG-04: enabled by default). */
export function activatePlugins(plugins: FrontendPlugin[]) {
  for (const p of plugins) {
    if (active.has(p.id)) continue
    p.activate(context)
    active.set(p.id, p)
  }
}

export const isActive = (id: string) => active.has(id)

/** Open handler for a Library entry, or null when the plugin has no UI surface here. */
export function openerOf(id: string): (() => void) | null {
  return active.get(id)?.open ?? null
}
