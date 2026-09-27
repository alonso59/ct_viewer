// Viewer: case editor, tools, layouts, overlays (VIEWER.md). NiiVue lives only in ./engine.
import i18n from '../../i18n'
import { keys, queryClient, type Project, type SegmentationSet } from '../../api'
import { refreshUrl, registry, toast, useWorkbench } from '../../shell'
import { useViewerSync, type ViewerTool } from '../../state'
import { codicon, ct } from '../../theme'
import { CaseEditor, type CaseParams } from './CaseEditor'
import { ImageSection } from './ImageSection'
import { LayersSection, WindowSection } from './Inspector'
import { CursorStatus, WindowStatus } from './StatusItems'
import { useViewerLocal } from './local'
import { isLayoutId, visibleViewports } from './model/layouts'
import type { ViewerContext } from './model/types'
import { LayoutMenu, OverlayToggles, ResetAndSnapshot, screenshot, ToolGroup, WindowPresets } from './Tools'
import { createElement, lazy, Suspense, type ComponentType } from 'react'

// The CT tools beyond the basics load with their strings on first render (NFR-07, VW-22/23)
const ctTools = () => Promise.all([import('./CtTools'), import('../../i18n/lazy')]).then(([m]) => m)
const lazyTool = (pick: (m: Awaited<ReturnType<typeof ctTools>>) => ComponentType): ComponentType => {
  const C = lazy(() => ctTools().then((m) => ({ default: pick(m) })))
  return () => createElement(Suspense, { fallback: null }, createElement(C))
}
/** VW-22: the whole CT tool bar, for Open mode */
export const CtToolbar = lazyTool((m) => m.default)

export { configureViewer } from './budget'
export { StandaloneViewer } from './StandaloneViewer'
export { applyProjectDisplay, resetDisplay } from './display'
export { ModalityChip } from './ModalityChip'
export type { ViewerContext } from './model/types'

/** VW-16: viewer context of the visible case tab, for CUR events (`context.viewer`) */
export function getViewerContext(): ViewerContext | null {
  return useViewerLocal.getState().active?.snapshot() ?? null
}

/** VW-19: the project's segmentation sets, from the cached query */
const segSets = (): SegmentationSet[] => {
  const pid = useWorkbench.getState().pid
  return pid ? (queryClient.getQueryData<SegmentationSet[]>(keys.segmentations(pid)) ?? []) : []
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
  registry.tool({ id: 'viewer.measure', order: 15, component: lazyTool((m) => m.MeasureTools) })
  registry.tool({ id: 'viewer.layout', order: 20, component: LayoutMenu })
  registry.tool({ id: 'viewer.overlay', order: 30, component: OverlayToggles })
  registry.tool({ id: 'viewer.wl', order: 40, component: WindowPresets })
  registry.tool({ id: 'viewer.wlInputs', order: 45, component: lazyTool((m) => m.WindowInputs) })
  registry.tool({ id: 'viewer.slab', order: 50, component: lazyTool((m) => m.SlabControls) })
  registry.tool({ id: 'viewer.header', order: 85, component: lazyTool((m) => m.HeaderInfo) })
  registry.tool({ id: 'viewer.reset', order: 90, component: () => createElement(ResetAndSnapshot) })

  registry.view({ id: 'image', title: 'view.image', icon: codicon('info'), order: 20, component: ImageSection, hideImageSection: true })
  registry.imageSectionContent({ id: 'viewer.image', order: 10, component: ImageSection })
  registry.inspector({ id: 'viewer.layers', title: 'inspector.layers', order: 20, component: LayersSection })
  registry.inspector({ id: 'viewer.wl', title: 'inspector.window', order: 30, component: WindowSection })
  registry.status({ id: 'viewer.cursor', align: 'right', order: 10, component: CursorStatus })
  registry.status({ id: 'viewer.wl', align: 'right', order: 20, component: WindowStatus })

  // A viewer is visible: a case tab or Open mode (VW-22: shortcuts work in both)
  const isCase = () => useViewerLocal.getState().active !== null
  // AUD-A2-02: `when: 'viewer'` keys need a shown viewer, not DOM focus inside it
  registry.context('viewer', () => useWorkbench.getState().active?.type === 'case' || isCase())
  const both = ['project', 'open'] as const
  const tools: [ViewerTool, string][] = [['pan', 'm'], ['window', 'w'], ['crosshair', 'c'], ['zoom', 'z']]
  for (const [tool, key] of tools)
    registry.command({
      id: `viewer.tool.${tool}`,
      title: `viewer.tool.${tool}`,
      category: 'cat.viewer',
      keybinding: key,
      when: 'viewer',
      scope: [...both],
      menuGroup: 2,
      run: () => useViewerSync.setState({ tool }),
    })
  registry.command({ id: 'viewer.cycleLayout', title: 'cmd.cycleLayout', category: 'cat.viewer', keybinding: 'l', when: 'viewer', scope: [...both], menuGroup: 1, enabled: isCase, run: () => useViewerSync.getState().cycleLayout() })
  registry.command({ id: 'viewer.reset', title: 'viewer.reset', category: 'cat.viewer', keybinding: 'r', when: 'viewer', scope: [...both], menuGroup: 1, enabled: isCase, run: () => useViewerSync.getState().reset() })
  // VW-26: fit the view under the pointer (else the maximized one); from the palette or a menu,
  // with no pointer over a view, every visible view
  const fitTarget = () => useViewerLocal.getState().hovered ?? useViewerSync.getState().maximized
  const fit = () => {
    const h = useViewerLocal.getState().active
    const tile = fitTarget()
    if (!h) return
    if (tile) h.fitView(tile)
    else {
      const s = useViewerSync.getState()
      for (const vp of visibleViewports(s.layout, s.maximized)) h.fitView(vp)
    }
  }
  registry.command({ id: 'viewer.fit', title: 'viewer.fit', category: 'cat.viewer', keybinding: 'f', when: 'viewer', scope: [...both], keywords: ['kw.zoom'], menuGroup: 1, enabled: isCase, run: fit })
  registry.command({ id: 'viewer.restore', title: 'viewer.restore', category: 'cat.viewer', keybinding: 'esc', when: 'viewer', scope: [...both], menu: false, enabled: () => useViewerSync.getState().maximized !== null, run: () => useViewerSync.setState({ maximized: null }) })
  registry.command({ id: 'viewer.screenshot', title: 'viewer.screenshot', category: 'cat.viewer', scope: [...both], menuGroup: 1, enabled: isCase, run: () => void screenshot() })
  registry.command({ id: 'viewer.toggleOverlay', title: 'viewer.overlay', category: 'cat.viewer', scope: [...both], keywords: ['kw.mask'], menuGroup: 3, enabled: isCase, run: () => useViewerSync.setState((s) => ({ overlay: !s.overlay })) })
  registry.command({ id: 'viewer.toggleOutline', title: 'viewer.outline', category: 'cat.viewer', scope: [...both], keywords: ['kw.mask'], menuGroup: 3, enabled: isCase, run: () => useViewerSync.setState((s) => ({ outline: !s.outline })) })
  // AUD-A1-06: switch the segmentation set shown (VW-19; the Layers section's choice)
  registry.command({
    id: 'viewer.nextSegSet',
    title: 'cmd.nextSegSet',
    category: 'cat.viewer',
    keywords: ['kw.segmentation', 'kw.mask'],
    menuGroup: 3,
    enabled: () => segSets().length > 1,
    run: () => {
      const pid = useWorkbench.getState().pid
      const sets = segSets()
      if (!pid || sets.length < 2) return
      const v = useViewerSync.getState()
      const cur = v.segChoice[pid] ?? queryClient.getQueryData<Project>(keys.project(pid))?.default_seg ?? 'imported'
      const next = sets[(sets.findIndex((x) => x.seg_id === cur) + 1) % sets.length]
      if (!next) return
      v.set({ segChoice: { ...v.segChoice, [pid]: next.seg_id } })
      toast({ message: i18n.t('viewer.segShown', { set: next.name || next.seg_id }) })
    },
  })
  for (let n = 1; n <= 9; n++)
    registry.command({
      id: `viewer.toggleLabel.${n}`,
      title: 'cmd.toggleLabel',
      titleArgs: { n: String(n) },
      category: 'cat.viewer',
      keybinding: String(n),
      when: 'viewer',
      menu: false,
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
