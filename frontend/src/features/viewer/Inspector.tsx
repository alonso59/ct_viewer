import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { useProject, useSegmentations } from '../../api'
import { NumberInput } from '../../lib'
import { openEditor, useWorkbench } from '../../shell'
import { useViewerSync, WL_PRESETS } from '../../state'

function AllLabels({ checked, mixed, onChange, label }: { checked: boolean; mixed: boolean; onChange: (checked: boolean) => void; label: string }) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = mixed
  }, [mixed])
  return <input ref={ref} type="checkbox" aria-label={label} checked={checked} onChange={(event) => onChange(event.target.checked)} />
}

export function LayersSection() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const project = useProject(pid).data
  const sets = useSegmentations(pid).data ?? []
  const v = useViewerSync()
  const preferred = v.segChoice[pid] ?? project?.default_seg
  const active = sets.some((set) => set.seg_id === preferred) ? (preferred ?? '') : (sets[0]?.seg_id ?? '')
  const segmentation = sets.find((set) => set.seg_id === active)
  const labels = (project?.label_map ?? []).filter((label) => {
    const values = Object.entries(segmentation?.label_mapping ?? {}).filter(([, value]) => value === label.value).map(([value]) => Number(value))
    return !(values.length ? values : [label.value]).every((value) => segmentation?.removed_labels?.includes(value))
  })
  const visible = labels.filter((label) => v.labelVisibility[label.value] ?? label.visible).length
  const setAll = (show: boolean) => v.set({
    labelVisibility: {
      ...v.labelVisibility,
      ...Object.fromEntries(labels.map((label) => [label.value, show])),
    },
  })
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 'var(--fs-panel)' }}>
      {sets.length ? (
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
      {labels.length ? (
        <label className="check">
          <AllLabels checked={visible === labels.length} mixed={visible > 0 && visible < labels.length} onChange={setAll} label={t('layers.toggleAll')} />
          {t(visible === labels.length ? 'layers.hideAll' : 'layers.showAll')}
        </label>
      ) : null}
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
      {!project?.read_only ? (
        <button type="button" className="btn btn-sm" onClick={() => openEditor('segmentations', {})}>{t('segmentation.manage')}</button>
      ) : null}
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
          <NumberInput className="input input-sm num" style={{ width: '100%' }} value={ww} onChange={(n) => n != null && setWindow(n, wl)} />
        </label>
        <label className="field">
          <span className="field-label">{t('viewer.level')}</span>
          <NumberInput className="input input-sm num" style={{ width: '100%' }} value={wl} onChange={(n) => n != null && setWindow(ww, n)} />
        </label>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {(Object.keys(WL_PRESETS) as (keyof typeof WL_PRESETS)[]).map((p) => (
          <button key={p} type="button" className="badge" aria-pressed={preset === p} data-tone={preset === p ? 'accent' : undefined} onClick={() => setPreset(p)}>
            {t(`viewer.preset.${p}`)}
          </button>
        ))}
      </div>
      <span className="muted small">{t('viewer.wlHint')}</span>
    </div>
  )
}
