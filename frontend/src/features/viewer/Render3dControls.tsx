import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Icon, codicon } from '../../theme'
import { useViewerSync } from '../../state'
import { useViewerLocal } from './local'
import { Render3dPanel } from './Render3dPanel'
import { PLANES } from './model/layouts'
import { DEFAULT_SCENE_3D, sceneDetail } from './model/scene3d'
import type { Scene3DOptions } from './model/types'
import type { MeshState } from './Viewport'

export function Render3dControls({ hasMask, canSurface, meshState, active = true }: { active?: boolean; hasMask: boolean; canSurface: boolean; meshState: MeshState }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLButtonElement>(null)
  const state = useViewerLocal()
  const crosshair = useViewerSync((s) => s.crosshair)
  const set = useViewerLocal.setState
  const scene = state.scene3d
  const patch = (p: Partial<Scene3DOptions>) => set({ scene3d: { ...scene, ...p } })
  const maskOnly = hasMask && !state.volume3d && state.mask3d
  return <span className="vp-3d-tools" onDoubleClick={(e) => e.stopPropagation()}>
    <button type="button" className="btn btn-sm vp-mask-only" disabled={!hasMask} aria-pressed={maskOnly} title={t('vw.render.maskOnlyHelp')} onClick={() => set({ volume3d: maskOnly, mask3d: true })}>
      <Icon spec={codicon('symbol-structure')} />{t('vw.render.maskOnly')}
    </button>
    <button ref={anchor} type="button" className="icon-btn vp-3d-controller" aria-label={t('vw.render.settings')} title={t('vw.render.settings')} aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(!open)}><Icon spec={codicon('settings-gear')} /></button>
    <Render3dPanel open={open && active} onClose={() => setOpen(false)} anchor={anchor}>
        <fieldset><legend>{t('vw.render.content')}</legend>
          <label><input type="checkbox" checked={!hasMask || state.volume3d} disabled={!hasMask} onChange={(e) => set({ volume3d: e.target.checked })} />{t('vw.render.volume')}</label>
          <label><input type="checkbox" checked={hasMask && state.mask3d} disabled={!hasMask} onChange={(e) => set({ mask3d: e.target.checked })} />{t('vw.render.mask')}</label>
          <label>{t('vw.render.ctOpacity')}<input type="range" min={0} max={1} step={0.05} value={state.ctOpacity} onChange={(e) => set({ ctOpacity: +e.target.value })} /><output>{t('vw.render.percent', { value: Math.round(state.ctOpacity * 100) })}</output></label>
          <label>{t('vw.render.blend')}<input type="range" min={0} max={1} step={0.05} value={state.blend} disabled={!hasMask} onChange={(e) => set({ blend: +e.target.value })} /><output>{t('vw.render.percent', { value: Math.round(state.blend * 100) })}</output></label>
          <label>{t('vw.render.maskStyle')}<select className="select" value={state.surfaces && canSurface ? 'surface' : 'volume'} disabled={!hasMask} onChange={(e) => set({ surfaces: e.target.value === 'surface' })}>
            <option value="volume">{t('vw.render.labelVolume')}</option><option value="surface" disabled={!canSurface}>{t('vw.render.surfaces')}</option>
          </select></label>
          {state.surfaces && canSurface && meshState !== 'idle' ? <span role="status" className="muted">{t(meshState === 'building' ? 'vw.meshBuilding' : 'vw.meshError')}</span> : null}
        </fieldset>
        <fieldset><legend>{t('vw.render.visibility')}</legend>
          <div className="seg" role="group" aria-label={t('vw.render.detail')}>
            {(['minimal', 'standard', 'full'] as const).map((level) => <button key={level} type="button" onClick={() => patch(sceneDetail(level))}>{t(`vw.render.detail_${level}`)}</button>)}
          </div>
          <label>{t('vw.render.background')}<select className="select" value={scene.background} onChange={(e) => patch({ background: e.target.value as Scene3DOptions['background'] })}>
            {(['slicer', 'black', 'white'] as const).map((bg) => <option key={bg} value={bg}>{t(`vw.render.background_${bg}`)}</option>)}
          </select></label>
          {(['orientationCube', 'axisLabels', 'bounds', 'axes'] as const).map((key) => <label key={key}><input type="checkbox" checked={scene[key]} onChange={(e) => patch({ [key]: e.target.checked })} />{t(`vw.render.${key}`)}</label>)}
          <label><input type="checkbox" checked={crosshair} onChange={(e) => useViewerSync.getState().set({ crosshair: e.target.checked })} />{t('vw.render.crosshair2d')}</label>
          <label>{t('vw.render.annotations')}<select className="select" value={scene.annotations} onChange={(e) => patch({ annotations: e.target.value as Scene3DOptions['annotations'] })}>
            {(['none', 'basic', 'full'] as const).map((level) => <option key={level} value={level}>{t(`vw.render.annotations_${level}`)}</option>)}
          </select></label>
        </fieldset>
        <fieldset><legend>{t('vw.render.slicePlanes')}</legend>
          {PLANES.map((plane) => <label key={plane}>{t(`viewer.plane.${plane}`)}<select className="select" value={scene.planes[plane]} onChange={(e) => patch({ planes: { ...scene.planes, [plane]: e.target.value } })}>
            {(['off', 'outline', 'slice'] as const).map((mode) => <option key={mode} value={mode}>{t(`vw.render.plane_${mode}`)}</option>)}
          </select></label>)}
          <p className="muted">{t('vw.render.slicePlanesHelp')}</p>
        </fieldset>
        <button type="button" className="btn btn-sm" onClick={() => set({ volume3d: true, mask3d: true, ctOpacity: 1, blend: 1, surfaces: true, scene3d: DEFAULT_SCENE_3D })}>{t('vw.render.reset')}</button>
    </Render3dPanel>
  </span>
}
