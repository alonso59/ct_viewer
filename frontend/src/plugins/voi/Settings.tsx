// `voi.extract` settings in the task tab: region, labels (the region's, or a custom pick from the
// segmentation set's active labels), the box preset and the output.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useProject, useSegmentations, useVoiRegions } from '../../api'
import { NumberInput, RadioSeg } from '../../lib'
import type { TaskSettingsProps } from '../../shell'
import { activeLabels, boxMode, chosenLabels, effectiveBox, fmtSize, keepLabelsOf, regionOf, resampleOf, skipExistingOf, withBoxMode, type BoxMode } from './model'
import './voi.css'

export default function VoiSettings({ pid, values, onChange, segId }: TaskSettingsProps) {
  const { t } = useTranslation()
  const project = useProject(pid).data
  const sets = useSegmentations(pid).data ?? []
  const regions = useVoiRegions().data ?? []
  const region = regions.find((r) => r.id === regionOf(values))
  const set = sets.find((s) => s.seg_id === (segId ?? project?.default_seg))
  const available = activeLabels(project?.label_map ?? [], set)
  const labels = chosenLabels(values, region, available.map((l) => l.name))
  const custom = Array.isArray(values.labels)
  const [customizing, setCustomizing] = useState(false)
  const mode = boxMode(values)
  const box = effectiveBox(values, region)
  const setSize = (i: number, v: number | null) => {
    const size = [...box.size] as [number, number, number]
    size[i] = v ?? 0
    onChange({ ...values, margin_mm: box.margin, min_size_mm: size })
  }
  const toggleLabel = (name: string) => onChange({ ...values, labels: labels.includes(name) ? labels.filter((n) => n !== name) : [...labels, name] })
  return (
    <div className="voi-settings">
      <div className="task-form">
        <label className="task-field">
          <span className="field-label">{t('voi.region')}</span>
          <select className="select" value={regionOf(values)} onChange={(e) => onChange({ ...values, region: e.target.value, labels: undefined, margin_mm: undefined, min_size_mm: undefined })}>
            {regions.map((r) => (
              <option key={r.id} value={r.id}>
                {t(`voi.regions.${r.id}`)}
              </option>
            ))}
          </select>
        </label>
        <div className="task-field">
          <span className="field-label">{t('voi.labels')}</span>
          <span className="voi-label-summary">
            {labels.length ? labels.join(', ') : <span className="field-error">{t('voi.noLabels')}</span>}
            <button type="button" className="link" aria-expanded={customizing} onClick={() => setCustomizing((c) => !c)}>
              {t(customizing ? 'voi.doneCustomizing' : 'voi.customize')}
            </button>
            {custom ? (
              <button type="button" className="link" onClick={() => onChange({ ...values, labels: undefined })}>
                {t('voi.regionLabels')}
              </button>
            ) : null}
          </span>
          <span className="muted task-help">{t(custom ? 'voi.labelsCustomHelp' : 'voi.labelsRegionHelp')}</span>
        </div>
      </div>
      {customizing ? (
        <fieldset className="voi-labels">
          <legend className="muted task-help">{t('voi.labelsInSet')}</legend>
          {available.length ? (
            <div className="voi-label-list">
              {available.map((l) => (
                <label key={l.value} className="voi-label">
                  <input type="checkbox" checked={labels.includes(l.name)} onChange={() => toggleLabel(l.name)} />
                  <span className="dot" style={{ background: l.color }} />
                  {l.name}
                </label>
              ))}
            </div>
          ) : (
            <span className="muted">{t('voi.noSetLabels')}</span>
          )}
        </fieldset>
      ) : null}
      <div className="task-field">
        <RadioSeg
          label={t('voi.box')}
          value={mode}
          onChange={(m: BoxMode) => onChange(withBoxMode(values, m, region))}
          options={[
            { value: 'recommended', label: t('voi.boxMode.recommended') },
            { value: 'tight', label: t('voi.boxMode.tight') },
            { value: 'custom', label: t('voi.boxMode.custom') },
          ]}
        />
        <span className="muted task-help">
          {box.size.every((v) => v === 0) ? t('voi.boxTightLine', { margin: box.margin }) : t('voi.boxLine', { size: fmtSize(box.size), margin: box.margin })}
        </span>
        {mode === 'custom' ? (
          <div className="voi-box-fields">
            <label className="voi-field">
              <span>{t('voi.margin')}</span>
              <NumberInput className="input input-sm num" value={box.margin} min={0} max={100} onChange={(n) => onChange({ ...values, margin_mm: n ?? 0, min_size_mm: box.size })} />
            </label>
            <fieldset className="voi-field voi-size">
              <legend>{t('voi.minSize')}</legend>
              {(['x', 'y', 'z'] as const).map((axis, i) => (
                <NumberInput key={axis} className="input input-sm num" aria-label={t(`voi.axis.${axis}`)} value={box.size[i]} min={0} max={1000} onChange={(n) => setSize(i, n)} />
              ))}
            </fieldset>
          </div>
        ) : null}
      </div>
      <div className="task-form">
        <label className="task-field">
          <span className="field-label">{t('voi.resample')}</span>
          <NumberInput className="input num" value={resampleOf(values)} min={0} max={10} step={0.25} onChange={(n) => onChange({ ...values, resample_mm: n ?? 0 })} />
          <span className="muted task-help">{t('voi.resampleHelp')}</span>
        </label>
        <label className="task-field voi-check">
          <span>
            <input type="checkbox" checked={keepLabelsOf(values)} onChange={(e) => onChange({ ...values, keep_labels: e.target.checked })} /> {t('voi.keepLabels')}
          </span>
          <span className="muted task-help">{t('voi.keepLabelsHelp')}</span>
        </label>
        <label className="task-field voi-check">
          <span>
            <input type="checkbox" checked={skipExistingOf(values)} onChange={(e) => onChange({ ...values, skip_existing: e.target.checked })} /> {t('voi.skipExisting')}
          </span>
          <span className="muted task-help">{t('voi.skipExistingHelp')}</span>
        </label>
      </div>
    </div>
  )
}
