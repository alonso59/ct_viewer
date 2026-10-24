// Import wizard, step 2 (IMP-03, SRC-01..06, SRC-17): the detected source adapters with their
// reasons, `nifti-files` options with pattern suggestions, the DICOM and sidecar choices.
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { DetectCandidate, NiftiOptions } from '../../../api'
import { ProblemCard, type ActionHandlers } from '../../../lib'
import { Icon, codicon } from '../../../theme'
import { CONVERTER_PATTERN, FOLDER_PATTERN, segments, subjectOf, suggestPatterns } from '../patternSuggest'
import { GROUP_COLOR, Highlight, PatternByExample } from './PatternByExample'

const EXAMPLES = 4

/** SRC-17: candidates from the sampled image paths; picking one only fills the field */
function PatternSuggester({ stems, current, onPick }: { stems: string[]; current: string | undefined; onPick: (pattern: string) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const cands = useMemo(() => suggestPatterns(stems), [stems])
  if (!open) {
    return (
      <button type="button" className="btn btn-sm justify-start" onClick={() => setOpen(true)}>
        <Icon spec={codicon('lightbulb')} />
        {t('import.suggestPattern')}
      </button>
    )
  }
  return (
    <div className="pattern-cands">
      <span className="muted small">
        {!stems.length ? t('import.suggestNone') : !cands.length ? t('import.suggestNoMatch') : t('import.suggestHelp')}
      </span>
      {cands.map((c) => (
        <button key={c.pattern} type="button" className="pattern-cand" data-checked={current === c.pattern} onClick={() => onPick(c.pattern)}>
          <span className="mono pattern-rx" title={c.pattern}>{c.pattern}</span>
          <span className="pattern-meta">
            {c.groups.map((g) => (
              <span key={g} className="mono pattern-group" style={{ color: GROUP_COLOR[g] }}>{g}</span>
            ))}
            <span className="muted">{t('import.suggestMatches', { n: c.matched, total: stems.length })}</span>
          </span>
          {stems
            .filter((s) => segments(c.pattern, subjectOf(c.pattern, s)))
            .slice(0, EXAMPLES)
            .map((s) => (
              <Highlight key={s} pattern={c.pattern} path={s} />
            ))}
        </button>
      ))}
    </div>
  )
}

const PREFILL_NOTE: Record<string, string> = { [CONVERTER_PATTERN]: 'import.nifti.patternPrefilled', [FOLDER_PATTERN]: 'import.nifti.patternPrefilledFolder' }

/** SRC-04 options: the pattern and mask template by example (SRC-17), as raw fields under
 *  "Advanced", case id source, modality */
function NiftiOptionsForm({ value, onChange, stems, prefilled, dir }: { value: NiftiOptions; onChange: (v: NiftiOptions) => void; stems: string[]; prefilled: boolean; dir: string | null }) {
  const { t } = useTranslation()
  const masks = Object.values(value.masks ?? {})
  const note = prefilled ? (value.mask_template ? 'import.nifti.patternPrefilledPaired' : PREFILL_NOTE[value.pattern ?? '']) : undefined
  return (
    <div className="wiz-nifti">
      {masks.length ? (
        <p className="muted panel-size m-0" role="note" >
          <Icon spec={codicon('layers')} /> {t('import.nifti.withMask', { mask: masks.join(', ') })}
        </p>
      ) : null}
      {dir ? <PatternByExample root={dir} stems={stems} value={value} onChange={onChange} /> : null}
      {note ? <span className="muted small" role="note">{t(note)}</span> : null}
      <details className="wiz-advanced" open={!dir}>
        <summary className="small">{t('import.byExample.advanced')}</summary>
        <label className="field">
          <span className="field-label">{t('import.nifti.pattern')}</span>
          <input className="input mono" value={value.pattern ?? ''} placeholder={t('import.nifti.patternDefault')} onChange={(e) => onChange({ ...value, pattern: e.target.value || undefined })} />
          <span className="muted small">{t('import.nifti.patternHelp')}</span>
        </label>
        <PatternSuggester stems={stems} current={value.pattern} onPick={(pattern) => onChange({ ...value, pattern })} />
        <label className="field">
          <span className="field-label">{t('import.nifti.maskTemplate')}</span>
          <input className="input mono" value={value.mask_template ?? ''} placeholder={t('import.nifti.maskTemplatePlaceholder')} onChange={(e) => onChange({ ...value, mask_template: e.target.value || undefined })} />
          <span className="muted small">{t('import.nifti.maskTemplateHelp')}</span>
        </label>
      </details>
      <div className="wiz-nifti-grid">
        <label className="field">
          <span className="field-label">{t('import.nifti.caseIdFrom')}</span>
          <select className="select" value={value.case_id_from ?? 'pattern'} onChange={(e) => onChange({ ...value, case_id_from: e.target.value as NiftiOptions['case_id_from'] })}>
            {(['pattern', 'stem', 'sequential'] as const).map((k) => (
              <option key={k} value={k}>{t(`import.nifti.from.${k}`)}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">{t('import.nifti.modality')}</span>
          <input className="input mono" value={value.modality ?? 'CT'} onChange={(e) => onChange({ ...value, modality: e.target.value.toUpperCase() })} />
        </label>
      </div>
    </div>
  )
}

/** IMP-03 (AUD-A1-15): the adapter in plain words, its reason on its own line; internal names in the tooltip */
function Candidates({ cands, value, onPick }: { cands: DetectCandidate[]; value: string | null; onPick: (a: string) => void }) {
  const { t } = useTranslation()
  return (
    <fieldset className="field preset-list bare">
      <legend className="field-label">{t('import.adapterTitle')}</legend>
      {cands.map((c) => {
        const key = c.adapter.replace('.', '_')
        return (
          <label key={c.adapter} className="preset adapter-option" data-checked={value === c.adapter} aria-disabled={!c.available} title={t(`import.adapterHint.${key}`, { defaultValue: c.adapter })}>
            <input type="radio" name="adapter" value={c.adapter} disabled={!c.available} checked={value === c.adapter} onChange={() => onPick(c.adapter)} />
            <span className="adapter-text">
              <strong>{t(`import.adapter.${key}`)}</strong>
              <span className="muted">{c.reason}{c.unavailable_reason ? ` — ${c.unavailable_reason}` : ''}</span>
            </span>
            <span className="badge ml-auto">{t(`import.confidence.${c.confidence}`)}</span>
          </label>
        )
      })}
    </fieldset>
  )
}

export function DetectStep(p: {
  path: string | null
  pending: boolean
  errors: unknown[]
  onAction: ActionHandlers
  /** The derived-folder dialog, when a conversion asks for one */
  derived: ReactNode
  cands: DetectCandidate[]
  adapter: string | null
  onAdapter: (a: string) => void
  nifti: NiftiOptions
  onNifti: (o: NiftiOptions) => void
  /** Sampled image paths without extension (SRC-17) */
  stems: string[]
  /** The chosen folder (null when one file was chosen): the root of the pattern by example */
  dir: string | null
  prefilled: boolean
  anonymize: boolean
  onAnonymize: (on: boolean) => void
  reconstruct: boolean
  onReconstruct: (on: boolean) => void
  ignored: Record<string, number> | undefined
}) {
  const { t } = useTranslation()
  return (
    <div>
      <h3>{t('import.detectTitle')}</h3>
      <p className="muted mono">{p.path}</p>
      {p.pending ? (
        <div className="empty">
          <Icon spec={codicon('loading')} className="codicon-modifier-spin" />
          {t('import.scanning')}
        </div>
      ) : null}
      {p.errors.map((e, k) => (e ? <ProblemCard key={k} error={e} onAction={p.onAction} /> : null))}
      {p.derived}
      {p.cands.length ? (
        <div className="wiz-grid mt-2">
          <Candidates cands={p.cands} value={p.adapter} onPick={p.onAdapter} />
          <div>
            {p.adapter === 'nifti-files' ? <NiftiOptionsForm value={p.nifti} onChange={p.onNifti} stems={p.stems} prefilled={p.prefilled} dir={p.dir} /> : null}
            {p.adapter === 'dicom.convert' ? (
              // AUD-A5-16: the same anonymize choice as the converter window (DCM-05, NFR-17)
              <label className="check mt-2">
                <input type="checkbox" checked={p.anonymize} onChange={(e) => p.onAnonymize(e.target.checked)} />
                <span>
                  {t('conv.anonymize')}
                  <span className="muted block small">{t('conv.phiNotice')}</span>
                </span>
              </label>
            ) : null}
            {p.adapter === 'metadata-v1' ? (
              <label className="check mt-2">
                <input type="checkbox" checked={p.reconstruct} onChange={(e) => p.onReconstruct(e.target.checked)} />
                <span>
                  {t('import.reconstruct')}
                  <span className="muted block small">{t('import.reconstructHelp')}</span>
                </span>
              </label>
            ) : null}
            {p.ignored && Object.keys(p.ignored).length ? (
              <p className="muted panel-size mt-2">
                {t('import.ignored', { list: Object.entries(p.ignored).map(([ext, n]) => `${n} ${ext}`).join(', ') })}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
