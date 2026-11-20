// `voi.extract` settings in the task tab: region, labels (the region's, or a custom pick from the
// segmentation set's active labels), the box preset, the output, the lesions measured in each crop
// and the training profile written at the end (tunable later in the run's results).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useProject, useSegmentations, useVoiRegions } from '../../api'
import { NumberInput, RadioSeg } from '../../lib'
import type { TaskSettingsProps } from '../../shell'
import {
  activeLabels,
  alphaOf,
  boxMode,
  chosenLabels,
  effectiveBox,
  fmtSize,
  huWindowOf,
  keepLabelsOf,
  lesionLabelsOf,
  measureLesionsOf,
  minLesionVoxelsOf,
  organLabelsOf,
  parsePercentiles,
  percentilesOf,
  regionOf,
  resampleOf,
  skipExistingOf,
  withBoxMode,
  type BoxMode,
  type Values,
} from './model'
import './voi.css'

/** Label names for one role: the region's by default, or a pick from the set's active labels */
function LabelPick({ title, help, chosen, isDefault, available, onPick, onReset }: {
  title: string
  help: string
  chosen: string[]
  isDefault: boolean
  available: { name: string; value: number; color: string }[]
  onPick: (names: string[]) => void
  onReset: () => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const toggle = (name: string) => onPick(chosen.includes(name) ? chosen.filter((n) => n !== name) : [...chosen, name])
  return (
    <div className="task-field">
      <span className="field-label">{title}</span>
      <span className="voi-label-summary">
        {chosen.length ? chosen.join(', ') : <span className="muted">{t('voi.lesions.none')}</span>}
        <button type="button" className="link" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {t(open ? 'voi.doneCustomizing' : 'voi.customize')}
        </button>
        {!isDefault ? (
          <button type="button" className="link" onClick={onReset}>
            {t('voi.regionLabels')}
          </button>
        ) : null}
      </span>
      <span className="muted task-help">{help}</span>
      {open ? (
        <fieldset className="voi-labels" aria-label={title}>
          {available.length ? (
            <div className="voi-label-list">
              {available.map((l) => (
                <label key={l.value} className="voi-label">
                  <input type="checkbox" checked={chosen.includes(l.name)} onChange={() => toggle(l.name)} />
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
    </div>
  )
}

/** Lesions measured in each crop and the sampling profile the run writes */
function LesionSettings({ values, onChange, region, available }: {
  values: Values
  onChange: (v: Values) => void
  region: { protect: string[]; organ: string[] } | undefined
  available: { name: string; value: number; color: string }[]
}) {
  const { t } = useTranslation()
  const measure = measureLesionsOf(values)
  const [pct, setPct] = useState(() => percentilesOf(values).join(', '))
  const parsed = parsePercentiles(pct)
  const [lo, hi] = huWindowOf(values)
  const set = (patch: Values) => onChange({ ...values, ...patch })
  return (
    <>
      <fieldset className="task-form voi-section">
        <legend className="field-label">{t('voi.lesions.title')}</legend>
        <label className="task-field voi-check">
          <span>
            <input type="checkbox" checked={measure} onChange={(e) => set({ measure_lesions: e.target.checked })} /> {t('voi.lesions.measure')}
          </span>
          <span className="muted task-help">{t('voi.lesions.measureHelp')}</span>
        </label>
        {measure ? (
          <>
            <LabelPick
              title={t('voi.lesions.labels')}
              help={t('voi.lesions.labelsHelp')}
              chosen={lesionLabelsOf(values, region)}
              isDefault={!(values.lesion_labels as string[] | undefined)?.length}
              available={available}
              onPick={(names) => set({ lesion_labels: names })}
              onReset={() => set({ lesion_labels: undefined })}
            />
            <LabelPick
              title={t('voi.lesions.organ')}
              help={t('voi.lesions.organHelp')}
              chosen={organLabelsOf(values, region)}
              isDefault={!(values.organ_labels as string[] | undefined)?.length}
              available={available}
              onPick={(names) => set({ organ_labels: names })}
              onReset={() => set({ organ_labels: undefined })}
            />
            <label className="task-field">
              <span className="field-label">{t('voi.lesions.minVoxels')}</span>
              <NumberInput className="input num" value={minLesionVoxelsOf(values)} min={1} max={100000} step={1} onChange={(n) => set({ min_lesion_voxels: n ?? 10 })} />
              <span className="muted task-help">{t('voi.lesions.minVoxelsHelp')}</span>
            </label>
          </>
        ) : null}
      </fieldset>
      {measure ? (
        <fieldset className="task-form voi-section">
          <legend className="field-label">{t('voi.profile.title')}</legend>
          <label className="task-field">
            <span className="field-label">{t('voi.profile.percentiles')}</span>
            <input
              className="input"
              value={pct}
              aria-invalid={!parsed}
              onChange={(e) => {
                setPct(e.target.value)
                const ps = parsePercentiles(e.target.value)
                if (ps) set({ bin_percentiles: ps })
              }}
            />
            {parsed ? <span className="muted task-help">{t('voi.profile.percentilesHelp', { n: parsed.length + 1 })}</span> : <span className="field-error">{t('voi.profile.percentilesInvalid')}</span>}
          </label>
          <label className="task-field">
            <span className="field-label">{t('voi.profile.alpha')}</span>
            <NumberInput className="input num" value={alphaOf(values)} min={0} max={1} step={0.1} onChange={(n) => set({ balancing_alpha: n ?? 0.5 })} />
            <span className="muted task-help">{t('voi.profile.alphaHelp')}</span>
          </label>
          <fieldset className="task-field voi-field voi-size">
            <legend className="field-label">{t('voi.profile.window')}</legend>
            <NumberInput className="input input-sm num" aria-label={t('voi.profile.windowLow')} value={lo} min={-1024} max={3071} onChange={(n) => set({ hu_window: [n ?? -100, hi] })} />
            <NumberInput className="input input-sm num" aria-label={t('voi.profile.windowHigh')} value={hi} min={-1024} max={3071} onChange={(n) => set({ hu_window: [lo, n ?? 300] })} />
            <span className="muted task-help">{lo < hi ? t('voi.profile.windowHelp') : <span className="field-error">{t('voi.profile.windowInvalid')}</span>}</span>
          </fieldset>
          <span className="muted task-help">{t('voi.profile.later')}</span>
        </fieldset>
      ) : null}
    </>
  )
}

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
      <LesionSettings values={values} onChange={onChange} region={region} available={available} />
    </div>
  )
}
