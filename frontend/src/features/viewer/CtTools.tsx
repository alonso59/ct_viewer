// CT tools beyond the basic tool bar (VW-17/22/23), loaded lazily with their strings (NFR-07):
// numeric W/L + the DICOM header window, slab MIP/MinIP/average, invert, measurements and header
// info. The same components serve the case tab (shell tool bar) and Open mode (CtToolbar).
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Dialog, IconButton, NumberInput } from '../../lib'
import { useViewerSync, type ViewerDisplay, type ViewerTool } from '../../state'
import { Icon, codicon } from '../../theme'
import { useViewerLocal } from './local'
import { dicomWindowOf } from './model/wl'
import { LayoutMenu, OverlayToggles, ResetAndSnapshot, ToolGroup, WindowPresets } from './Tools'

const useEnabled = () => useViewerLocal((s) => s.active !== null)
const SLABS: ViewerDisplay['slab']['mode'][] = ['none', 'mip', 'minip', 'avg']
const MEASURE: { id: ViewerTool; icon: string }[] = [
  { id: 'distance', icon: 'symbol-ruler' },
  { id: 'angle', icon: 'triangle-up' },
  { id: 'roi', icon: 'circle-large-outline' },
]

/** VW-22: numeric W/L and the DICOM header window of the visible item */
export function WindowInputs() {
  const { t } = useTranslation()
  const { ww, wl, setWindow } = useViewerSync()
  const item = useViewerLocal((s) => s.info?.item)
  const header = item ? dicomWindowOf(item) : null
  const enabled = useEnabled()
  return (
    <>
      <label className="toolbar-num" title={t('ct.ww')}>
        {t('ct.w')}
        <NumberInput className="input input-sm num" min={1} aria-label={t('ct.ww')} disabled={!enabled} value={ww} onChange={(n) => n != null && setWindow(n || 1, wl)} />
      </label>
      <label className="toolbar-num" title={t('ct.wlLevel')}>
        {t('ct.l')}
        <NumberInput className="input input-sm num" aria-label={t('ct.wlLevel')} disabled={!enabled} value={wl} onChange={(n) => n != null && setWindow(ww, n)} />
      </label>
      {header ? (
        <button type="button" className="btn btn-sm" disabled={!enabled} title={t('ct.dicomWindowHelp', { ww: header[0], wl: header[1] })} onClick={() => setWindow(header[0], header[1])}>
          {t('ct.dicomWindow')}
        </button>
      ) : null}
      <span className="toolbar-sep" />
    </>
  )
}

/** VW-23: slab projection with a thickness in mm, and invert */
export function SlabControls() {
  const { t } = useTranslation()
  const display = useViewerSync((s) => s.display)
  const set = (p: Partial<ViewerDisplay>) => useViewerSync.setState((s) => ({ display: { ...s.display, ...p } }))
  const enabled = useEnabled()
  return (
    <>
      <Menu.Root>
        <Menu.Trigger className="toolbar-select" disabled={!enabled} aria-label={t('ct.slab')}>
          <Icon spec={codicon('layers-active')} />
          {t(`ct.slabMode.${display.slab.mode}`)}
          <Icon spec={codicon('chevron-down')} />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="overlay menu" sideOffset={4} align="start">
            {SLABS.map((m) => (
              <Menu.Item key={m} className="menu-item" onSelect={() => set({ slab: { ...display.slab, mode: m } })}>
                {t(`ct.slabMode.${m}`)}
                {m === display.slab.mode ? <span className="kbd"><Icon spec={codicon('check')} /></span> : null}
              </Menu.Item>
            ))}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      {display.slab.mode !== 'none' ? (
        <label className="toolbar-num" title={t('ct.thickness')}>
          <NumberInput className="input input-sm num" min={1} max={100} aria-label={t('ct.thickness')} value={display.slab.mm} onChange={(n) => n != null && set({ slab: { ...display.slab, mm: Math.max(1, Math.min(100, n || 1)) } })} />
          {t('ct.mm')}
        </label>
      ) : null}
      <IconButton icon={codicon('color-mode')} label={t('ct.invert')} pressed={enabled && display.invert} disabled={!enabled} onClick={() => set({ invert: !display.invert })} />
      <span className="toolbar-sep" />
    </>
  )
}

/** VW-17: distance, angle and ROI mean/SD; the drawn ones clear with the item or on request */
export function MeasureTools() {
  const { t } = useTranslation()
  const tool = useViewerSync((s) => s.tool)
  const enabled = useEnabled()
  return (
    <>
      {MEASURE.map((m) => (
        <IconButton key={m.id} icon={codicon(m.icon)} label={t(`ct.measure.${m.id}`)} pressed={enabled && tool === m.id} disabled={!enabled} onClick={() => useViewerSync.setState({ tool: m.id })} />
      ))}
      <IconButton icon={codicon('clear-all')} label={t('ct.clearMeasures')} disabled={!enabled} onClick={() => useViewerSync.setState((s) => ({ measureClear: s.measureClear + 1 }))} />
      <span className="toolbar-sep" />
    </>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <tr>
      <th>{k}</th>
      <td className="mono">{v}</td>
    </tr>
  )
}

/** A DICOM JSON value as text (PS3.18 F.2: `Value` array, `Alphabetic` person names) */
function tagValue(el: unknown): string {
  const vals = (el as { Value?: unknown[] } | undefined)?.Value ?? []
  return vals.map((x) => (typeof x === 'object' && x !== null ? ((x as { Alphabetic?: string }).Alphabetic ?? JSON.stringify(x)) : String(x))).join(' \\ ')
}

/** VW-22: NIfTI header facts of the item and, on demand, its DICOM tags */
export function HeaderInfo() {
  const { t } = useTranslation()
  const info = useViewerLocal((s) => s.info)
  const enabled = useEnabled()
  const [open, setOpen] = useState(false)
  const [tags, setTags] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const g = info?.item.geometry
  const load = () => {
    setError(null)
    info?.tags?.().then(setTags, (e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }
  return (
    <>
      <IconButton icon={codicon('info')} label={t('ct.header')} disabled={!enabled || !info} onClick={() => { setTags(null); setOpen(true) }} />
      {open && info ? (
        <Dialog open onOpenChange={setOpen} title={t('ct.headerTitle', { name: info.item.item_id })} icon={codicon('info')} size="lg">
          <table className="ct-header">
            <tbody>
              <Row k={t('ct.modality')} v={info.item.modality ?? '—'} />
              <Row k={t('ct.shape')} v={g?.shape.join(' × ') ?? '—'} />
              <Row k={t('ct.spacing')} v={g?.spacing.map((s) => s.toFixed(3)).join(' × ') ?? '—'} />
              <Row k={t('ct.dtype')} v={g?.dtype ?? '—'} />
              <Row k={t('ct.orientation')} v={g?.orientation ?? '—'} />
            </tbody>
          </table>
          {info.tags ? (
            tags ? (
              <div className="ct-tags">
                <table className="ct-header">
                  <tbody>
                    {Object.entries(tags).filter(([k]) => /^[0-9A-F]{8}$/.test(k)).map(([k, el]) => <Row key={k} k={`(${k.slice(0, 4)},${k.slice(4)}) ${(el as { vr?: string }).vr ?? ''}`} v={tagValue(el)} />)}
                  </tbody>
                </table>
              </div>
            ) : (
              <button type="button" className="btn btn-sm" onClick={load}>{t('ct.loadTags')}</button>
            )
          ) : <p className="muted">{t('ct.noTags')}</p>}
          {error ? <div className="error-card">{error}</div> : null}
          <p className="muted ct-phi">{t('ct.phi')}</p>
        </Dialog>
      ) : null}
    </>
  )
}

/** The CT tool bar for Open mode (VW-22: the same tools as the case tab) */
export default function CtToolbar() {
  return (
    <div className="toolbar ct-toolbar" role="toolbar">
      <ToolGroup />
      <MeasureTools />
      <LayoutMenu />
      <OverlayToggles />
      <WindowPresets />
      <WindowInputs />
      <SlabControls />
      <HeaderInfo />
      <ResetAndSnapshot standalone />
    </div>
  )
}
