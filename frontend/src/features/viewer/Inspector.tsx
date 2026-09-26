// Inspector sections contributed by the viewer: layers (VW-07) and window/level (VW-05)
import { useTranslation } from 'react-i18next'

import { useProject, useSegmentations } from '../../api'
import { useWorkbench } from '../../shell'
import { useViewerSync, WL_PRESETS } from '../../state'

export function LayersSection() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const project = useProject(pid).data
  const labels = project?.label_map ?? []
  const sets = useSegmentations(pid).data ?? []
  const v = useViewerSync()
  // VW-19: the choice is per project (AUD-A5-05)
  const active = v.segChoice[pid] ?? project?.default_seg ?? 'imported'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 'var(--fs-panel)' }}>
      {sets.length > 1 ? (
        <label className="field">
          <span className="field-label">{t('layers.segSet')}</span>
          <select className="select input-sm" value={active} onChange={(e) => v.set({ segChoice: { ...v.segChoice, [pid]: e.target.value } })}>
            {sets.map((s) => (
              <option key={s.seg_id} value={s.seg_id}>
                {t('layers.segOption', { name: s.name || s.seg_id, n: s.n_items })}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <label className="check">
        <input type="checkbox" checked={v.overlay} onChange={(e) => v.set({ overlay: e.target.checked })} />
        {t('viewer.overlay')}
      </label>
      <label className="field">
        <span className="field-label">{t('layers.globalOpacity', { v: Math.round(v.overlayOpacity * 100) })}</span>
        <input type="range" min={0} max={1} step={0.05} value={v.overlayOpacity} onChange={(e) => v.set({ overlayOpacity: +e.target.value })} />
      </label>
      {labels.map((l, i) => {
        const visible = v.labelVisibility[l.value] ?? l.visible
        const op = v.labelOpacity[l.value] ?? l.opacity
        return (
          <div key={l.value} style={{ display: 'grid', gridTemplateColumns: 'auto auto 1fr 80px', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" aria-label={l.name} checked={visible} onChange={() => v.toggleLabel(l.value, l.visible)} />
            <span className="dot" style={{ background: l.color }} />
            <span>
              {l.name} <kbd className="key">{i + 1}</kbd>
            </span>
            <input type="range" aria-label={t('layers.opacity', { name: l.name })} min={0} max={0.5} step={0.01} value={op} onChange={(e) => v.set({ labelOpacity: { ...v.labelOpacity, [l.value]: +e.target.value } })} />
          </div>
        )
      })}
    </div>
  )
}

export function WindowSection() {
  const { t } = useTranslation()
  const { ww, wl, setWindow, setPreset, preset } = useViewerSync()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 8 }}>
        <label className="field">
          <span className="field-label">{t('viewer.width')}</span>
          <input className="input input-sm num" style={{ width: '100%' }} type="number" value={ww} onChange={(e) => setWindow(+e.target.value, wl)} />
        </label>
        <label className="field">
          <span className="field-label">{t('viewer.level')}</span>
          <input className="input input-sm num" style={{ width: '100%' }} type="number" value={wl} onChange={(e) => setWindow(ww, +e.target.value)} />
        </label>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {(Object.keys(WL_PRESETS) as (keyof typeof WL_PRESETS)[]).map((p) => (
          <button key={p} type="button" className="badge" aria-pressed={preset === p} data-tone={preset === p ? 'accent' : undefined} onClick={() => setPreset(p)}>
            {t(`viewer.preset.${p}`)}
          </button>
        ))}
      </div>
      <span className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t('viewer.wlHint')}</span>
    </div>
  )
}
