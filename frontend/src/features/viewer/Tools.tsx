// Viewer tool bar items (UI-06, VW-10): tools, layout, overlay, W/L presets, reset, screenshot.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useTranslation } from 'react-i18next'

import { IconButton } from '../../lib'
import { bindingOf, formatChord, registry, useWorkbench } from '../../shell'
import { useLayout, useViewerSync, WL_PRESETS, type LayoutId, type ViewerTool } from '../../state'
import { CtIcon, Icon, codicon, ct, type CtIconName, type IconSpec } from '../../theme'
import { useViewerLocal } from './local'
import { ModalityChip } from './ModalityChip'

const useEnabled = () => useWorkbench((s) => s.active?.type === 'case')
const chord = (id: string) => {
  const c = registry.commands.get(id)
  return c ? formatChord(bindingOf(c)) : undefined
}

const TOOLS: { id: ViewerTool; icon: IconSpec; cmd: string }[] = [
  { id: 'pan', icon: codicon('move'), cmd: 'viewer.tool.pan' },
  { id: 'window', icon: ct('window-level'), cmd: 'viewer.tool.window' },
  { id: 'crosshair', icon: ct('crosshair'), cmd: 'viewer.tool.crosshair' },
  { id: 'zoom', icon: codicon('zoom-in'), cmd: 'viewer.tool.zoom' },
]

export function ToolGroup() {
  const { t } = useTranslation()
  const tool = useViewerSync((s) => s.tool)
  const set = useViewerSync((s) => s.set)
  const enabled = useEnabled()
  return (
    <>
      {TOOLS.map((x) => (
        <IconButton key={x.id} icon={x.icon} label={t(`viewer.tool.${x.id}`)} shortcut={chord(x.cmd)} pressed={enabled && tool === x.id} disabled={!enabled} onClick={() => set({ tool: x.id })} />
      ))}
      <span className="toolbar-sep" />
    </>
  )
}

export const LAYOUT_ICONS: Record<LayoutId, CtIconName> = {
  'four-up': 'layout-four-up',
  conventional: 'layout-conventional',
  'three-mpr': 'layout-three-mpr',
  'one-up-axial': 'plane-axial',
  'one-up-sagittal': 'plane-sagittal',
  'one-up-coronal': 'plane-coronal',
  'one-up-3d': 'view-3d',
}

export function LayoutMenu() {
  const { t } = useTranslation()
  const layout = useViewerSync((s) => s.layout)
  const set = useViewerSync((s) => s.set)
  const enabled = useEnabled()
  return (
    <>
      <Menu.Root>
        <Menu.Trigger className="toolbar-select" disabled={!enabled} title={`${t('viewer.layoutLabel')} (${chord('viewer.cycleLayout') ?? ''})`}>
          <CtIcon name={LAYOUT_ICONS[layout]} />
          {t(`viewer.layout.${layout}`)}
          <Icon spec={codicon('chevron-down')} />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="overlay menu" sideOffset={4} align="start">
            {(Object.keys(LAYOUT_ICONS) as LayoutId[]).map((l) => (
              <Menu.Item key={l} className="menu-item" onSelect={() => set({ layout: l, maximized: null })}>
                <CtIcon name={LAYOUT_ICONS[l]} />
                {t(`viewer.layout.${l}`)}
                {l === layout ? <span className="kbd"><Icon spec={codicon('check')} /></span> : null}
              </Menu.Item>
            ))}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      <span className="toolbar-sep" />
    </>
  )
}

export function OverlayToggles() {
  const { t } = useTranslation()
  const { overlay, outline, crosshair, set } = useViewerSync()
  const linkZoom = useViewerLocal((s) => s.linkZoom)
  const enabled = useEnabled()
  return (
    <>
      <IconButton icon={ct('label-overlay')} label={t('viewer.overlay')} pressed={enabled && overlay} disabled={!enabled} onClick={() => set({ overlay: !overlay })} />
      <IconButton icon={ct('label-outline')} label={t('viewer.outline')} pressed={enabled && outline} disabled={!enabled || !overlay} onClick={() => set({ outline: !outline })} />
      <IconButton icon={ct('crosshair-lines')} label={t('viewer.crosshairToggle')} pressed={enabled && crosshair} disabled={!enabled} onClick={() => set({ crosshair: !crosshair })} />
      <IconButton icon={codicon('link')} label={t('vw.linkZoom')} pressed={enabled && linkZoom} disabled={!enabled} onClick={() => useViewerLocal.setState({ linkZoom: !linkZoom })} />
      <span className="toolbar-sep" />
    </>
  )
}

export function WindowPresets() {
  const { t } = useTranslation()
  const { preset, ww, wl, setPreset } = useViewerSync()
  const enabled = useEnabled()
  return (
    <>
      <span className="toolbar-label">{t('viewer.wl')}</span>
      <Menu.Root>
        <Menu.Trigger className="toolbar-select" disabled={!enabled}>
          <CtIcon name="window-level" />
          {preset === 'custom' ? t('viewer.wlCustom', { ww, wl }) : t(`viewer.preset.${preset}`)}
          <Icon spec={codicon('chevron-down')} />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="overlay menu" sideOffset={4} align="start">
            {(Object.keys(WL_PRESETS) as (keyof typeof WL_PRESETS)[]).map((p) => (
              <Menu.Item key={p} className="menu-item" onSelect={() => setPreset(p)}>
                {t(`viewer.preset.${p}`)}
                <span className="kbd">{t('viewer.wlValues', { ww: WL_PRESETS[p][0], wl: WL_PRESETS[p][1] })}</span>
              </Menu.Item>
            ))}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      <ModalityChip />
      <span className="toolbar-sep" />
    </>
  )
}

export function ResetAndSnapshot() {
  const { t } = useTranslation()
  const enabled = useEnabled()
  const inspector = useLayout((s) => s.inspectorVisible)
  return (
    <>
      <IconButton icon={codicon('discard')} label={t('viewer.reset')} shortcut={chord('viewer.reset')} disabled={!enabled} onClick={() => useViewerSync.getState().reset()} />
      <IconButton icon={codicon('device-camera')} label={t('viewer.screenshot')} disabled={!enabled} onClick={() => void screenshot()} />
      <span style={{ flex: 1 }} />
      <IconButton icon={codicon('layout-sidebar-right')} label={t('cmd.toggleInspector')} shortcut={chord('workbench.toggleInspector')} pressed={inspector} onClick={() => useLayout.getState().toggle('inspectorVisible')} />
    </>
  )
}

/** VW-10: PNG of the visible viewports as rendered by the engine (download, no network) */
export async function screenshot() {
  const blob = await useViewerLocal.getState().active?.screenshot()
  if (!blob) return
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const { activeItemId } = useViewerSync.getState()
  a.download = `${activeItemId ?? 'viewer'}.png`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
