// Viewer: case editor, tools, layouts, overlays (VIEWER.md). NiiVue lives only in ./engine.
import { keys, queryClient, type Project } from '../../api'
import { refreshUrl, registry, useWorkbench } from '../../shell'
import { useViewerSync, type ViewerTool } from '../../state'
import { codicon, ct } from '../../theme'
import { CaseEditor, type CaseParams } from './CaseEditor'
import { ImageSection } from './ImageSection'
import { LayersSection, WindowSection } from './Inspector'
import { CursorStatus, WindowStatus } from './StatusItems'
import { useViewerLocal } from './local'
import { isLayoutId } from './model/layouts'
import type { ViewerContext } from './model/types'
import { LayoutMenu, OverlayToggles, ResetAndSnapshot, screenshot, ToolGroup, WindowPresets } from './Tools'
import './i18n'

export { PLANE_COLOR } from './Viewport'
export { configureViewer } from './budget'
export type { ViewerContext, ViewerHandle } from './model/types'

/** VW-16: viewer context of the visible case tab, for CUR events (`context.viewer`) */
export function getViewerContext(): ViewerContext | null {
  return useViewerLocal.getState().active?.snapshot() ?? null
}

/** Label map for the 1–9 keys, from the cached project query */
const projectLabels = (pid: string) => queryClient.getQueryData<Project>(keys.project(pid))?.label_map ?? []

export function registerViewer() {
  registry.editor<CaseParams>({
    type: 'case',
    component: CaseEditor,
    id: (p) => `case:${p.caseId}`,
    title: (p) => p.caseId,
    icon: () => ct('layout-four-up'),
    path: (pid, p) => {
      const sp = new URLSearchParams()
      if (p.itemId) sp.set('item', p.itemId)
      sp.set('layout', useViewerSync.getState().layout)
      return `/p/${pid}/case/${p.caseId}?${sp.toString()}`
    },
    match: (path, sp) => {
      const m = /^\/case\/([^/]+)$/.exec(path)
      if (!m?.[1]) return null
      const layout = sp.get('layout')
      if (isLayoutId(layout)) useViewerSync.setState({ layout })
      return { caseId: m[1], itemId: sp.get('item') }
    },
  })

  registry.tool({ id: 'viewer.tools', order: 10, component: ToolGroup })
  registry.tool({ id: 'viewer.layout', order: 20, component: LayoutMenu })
  registry.tool({ id: 'viewer.overlay', order: 30, component: OverlayToggles })
  registry.tool({ id: 'viewer.wl', order: 40, component: WindowPresets })
  registry.tool({ id: 'viewer.reset', order: 90, component: ResetAndSnapshot })

  registry.view({ id: 'image', title: 'view.image', icon: codicon('info'), order: 20, component: ImageSection, hideImageSection: true })
  registry.imageSectionContent({ id: 'viewer.image', order: 10, component: ImageSection })
  registry.inspector({ id: 'viewer.layers', title: 'inspector.layers', order: 20, component: LayersSection })
  registry.inspector({ id: 'viewer.wl', title: 'inspector.window', order: 30, component: WindowSection })
  registry.status({ id: 'viewer.cursor', align: 'right', order: 10, component: CursorStatus })
  registry.status({ id: 'viewer.wl', align: 'right', order: 20, component: WindowStatus })

  const isCase = () => useWorkbench.getState().active?.type === 'case'
  const tools: [ViewerTool, string][] = [['pan', 'm'], ['window', 'w'], ['crosshair', 'c'], ['zoom', 'z']]
  for (const [tool, key] of tools)
    registry.command({
      id: `viewer.tool.${tool}`,
      title: `viewer.tool.${tool}`,
      category: 'cat.viewer',
      keybinding: key,
      when: 'viewer',
      run: () => useViewerSync.setState({ tool }),
    })
  registry.command({ id: 'viewer.cycleLayout', title: 'cmd.cycleLayout', category: 'cat.viewer', keybinding: 'l', when: 'viewer', menu: 'view', menuGroup: 3, enabled: isCase, run: () => useViewerSync.getState().cycleLayout() })
  registry.command({ id: 'viewer.reset', title: 'viewer.reset', category: 'cat.viewer', keybinding: 'r', when: 'viewer', menu: 'view', menuGroup: 3, enabled: isCase, run: () => useViewerSync.getState().reset() })
  registry.command({ id: 'viewer.restore', title: 'viewer.restore', category: 'cat.viewer', keybinding: 'esc', when: 'viewer', enabled: () => useViewerSync.getState().maximized !== null, run: () => useViewerSync.setState({ maximized: null }) })
  registry.command({ id: 'viewer.screenshot', title: 'viewer.screenshot', category: 'cat.viewer', menu: 'view', menuGroup: 3, enabled: isCase, run: () => void screenshot() })
  registry.command({ id: 'viewer.toggleOverlay', title: 'viewer.overlay', category: 'cat.viewer', enabled: isCase, run: () => useViewerSync.setState((s) => ({ overlay: !s.overlay })) })
  registry.command({ id: 'viewer.toggleOutline', title: 'viewer.outline', category: 'cat.viewer', enabled: isCase, run: () => useViewerSync.setState((s) => ({ outline: !s.outline })) })
  for (let n = 1; n <= 9; n++)
    registry.command({
      id: `viewer.toggleLabel.${n}`,
      title: 'cmd.toggleLabel',
      category: 'cat.viewer',
      keybinding: String(n),
      when: 'viewer',
      run: () => {
        const pid = useWorkbench.getState().pid
        const label = pid ? projectLabels(pid)[n - 1] : undefined
        if (label) useViewerSync.getState().toggleLabel(label.value, label.visible)
      },
    })

  // The layout is part of the case URL (VW-01)
  useViewerSync.subscribe((s, prev) => {
    if (s.layout !== prev.layout) refreshUrl()
  })
}
