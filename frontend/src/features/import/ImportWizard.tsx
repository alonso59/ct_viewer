// Import wizard (IMP-01..05, SRC-01..06): a folder or one file (server browser, API-10) → detected
// source adapters (API-19) → preview (API-11; `nifti-files` options with a live parse) → commit
// (API-12) + indexing job (SSE progress, API-40). Refusals show their cause and next actions (UI-18).
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { create } from 'zustand'

import {
  api,
  useCommitImport,
  useDetect,
  useFsList,
  useImportPreview,
  useJobs,
  type DetectCandidate,
  type ImportAdapter,
  type ImportPreview,
  type NiftiOptions,
  type PreviewRequest,
  type RootRole,
} from '../../api'
import { Dialog, ProblemCard, Progress } from '../../lib'
import { toast } from '../../shell'
import { useReviewer } from '../../state'
import { DerivedRootDialog } from './DerivedRootDialog'
import { Icon, codicon } from '../../theme'
import './import.css'

export interface WizardPrefill {
  path: string
  adapter?: string
  /** SRC-15 "Add to project…": keep the project's other sources */
  add?: boolean
}

interface WizardState {
  pid: string | null
  prefill: WizardPrefill | null
  open: (pid: string, prefill?: WizardPrefill) => void
  close: () => void
}
export const useImportWizard = create<WizardState>()((set) => ({
  pid: null,
  prefill: null,
  open: (pid, prefill) => set({ pid, prefill: prefill ?? null }),
  close: () => set({ pid: null, prefill: null }),
}))

const STEPS = ['root', 'detect', 'preview', 'index'] as const
type Step = (typeof STEPS)[number]
const MAX_ERRORS = 50
/** SRC-02: files the browser lets you pick (folders are always navigable) */
const ACCEPTED = /\.(nii|nii\.gz|npy|dcm)$/i
const IMPORTABLE = new Set<string>(['metadata-v1', 'nifti-files'])

/** IMP-01: browse folders under ALLOWED_DATA_ROOTS (or ALLOWED_DERIVED_ROOTS); `null` = the roots */
export function FolderBrowser({
  path,
  onPath,
  selected,
  onSelectFile,
  role = 'source',
}: {
  path: string | null
  onPath: (p: string | null) => void
  /** Highlighted file (single-file selection, SRC-05) */
  selected?: string | null
  /** Makes accepted files clickable */
  onSelectFile?: (p: string) => void
  role?: RootRole
}) {
  const { t } = useTranslation()
  const { data, isLoading, isError, error } = useFsList(path, role)
  return (
    <div className="fs">
      <div className="fs-path mono" title={path ?? ''}>
        <Icon spec={codicon('folder-opened')} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', direction: 'rtl', textAlign: 'left' }}>
          {path ?? t('import.allowedRootsTitle')}
        </span>
      </div>
      <div className="fs-list" role="listbox" aria-label={t('import.folders')}>
        {path !== null ? (
          <button type="button" className="list-row" onClick={() => onPath(data?.parent ?? null)}>
            <Icon spec={codicon('arrow-up')} />
            {t('import.up')}
          </button>
        ) : null}
        {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
        {isError ? <ProblemCard error={error} /> : null}
        {data && data.entries.length === 0 ? <div className="empty">{t(path === null ? 'import.noRoots' : 'import.emptyFolder')}</div> : null}
        {data?.entries.map((e) => {
          const pickable = e.kind === 'file' && !!onSelectFile && ACCEPTED.test(e.name)
          return (
            <button
              key={e.path}
              type="button"
              className="list-row"
              aria-selected={selected === e.path}
              disabled={e.kind === 'file' && !pickable}
              onClick={() => (e.kind === 'dir' ? onPath(e.path) : onSelectFile?.(e.path))}
              title={e.path}
            >
              <Icon spec={codicon(e.kind === 'dir' ? 'folder' : 'file')} />
              <span>{e.name}</span>
              {e.has_metadata ? <span className="badge" data-tone="ok" style={{ marginLeft: 'auto' }}>{t('import.hasMetadata')}</span> : null}
              {selected === e.path ? <Icon spec={codicon('check')} style={{ marginLeft: 'auto' }} /> : null}
            </button>
          )
        })}
        {data?.truncated ? <div className="muted" style={{ padding: '4px 12px' }}>{t('import.truncated')}</div> : null}
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t(role === 'derived' ? 'import.allowedDerived' : 'import.allowedRoots')}</div>
    </div>
  )
}

type Uploads = NonNullable<PreviewRequest['files']>

/** IMP-02 alternative: upload the metadata files (images stay on the server) */
function UploadFields({ files, onFiles }: { files: Partial<Uploads>; onFiles: (f: Partial<Uploads>) => void }) {
  const { t } = useTranslation()
  const pick = (k: keyof Uploads) => (e: ChangeEvent<HTMLInputElement>) => onFiles({ ...files, [k]: e.target.files?.[0] ?? null })
  return (
    <div className="upload-grid">
      <label className="field">
        <span className="field-label">{t('import.upload.metadata')}</span>
        <input type="file" accept=".jsonl,.json" onChange={pick('metadata')} />
      </label>
      <label className="field">
        <span className="field-label">{t('import.upload.phase')}</span>
        <input type="file" accept=".json" onChange={pick('phase')} />
      </label>
      <label className="field">
        <span className="field-label">{t('import.upload.voi')}</span>
        <input type="file" accept=".jsonl" onChange={pick('voi_catalog')} />
      </label>
    </div>
  )
}

function Mapping({ preview }: { preview: ImportPreview }) {
  const { t } = useTranslation()
  const m = preview.field_mapping
  const rows: [string, string][] = [
    ['image', m.image ?? '—'],
    ['mask', m.seg ? t(`import.seg.${m.seg}`) : '—'],
    ['phase', m.phase?.length ? m.phase.join(' → ') : '—'],
    ['side', m.side ?? '—'],
  ]
  return (
    <table className="table">
      <tbody>
        {rows.map(([field, source]) => (
          <tr key={field}>
            <td>{t(`import.field.${field}`)}</td>
            <td className="muted"><Icon spec={codicon('arrow-left')} /></td>
            <td className="mono">{source}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** SRC-04 options: pattern (nnU-Net style by default), case id source, modality */
function NiftiOptionsForm({ value, onChange }: { value: NiftiOptions; onChange: (v: NiftiOptions) => void }) {
  const { t } = useTranslation()
  return (
    <div style={{ display: 'grid', gap: 10, marginTop: 8 }}>
      <label className="field">
        <span className="field-label">{t('import.nifti.pattern')}</span>
        <input className="input mono" value={value.pattern ?? ''} placeholder={t('import.nifti.patternDefault')} onChange={(e) => onChange({ ...value, pattern: e.target.value || undefined })} />
        <span className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t('import.nifti.patternHelp')}</span>
      </label>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
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

function NiftiSample({ p }: { p: ImportPreview }) {
  const { t } = useTranslation()
  return (
    <>
      <table className="table">
        <thead>
          <tr>
            <th>{t('import.nifti.file')}</th>
            <th>{t('import.nifti.case')}</th>
            <th>{t('import.nifti.scan')}</th>
            <th>{t('import.nifti.modality')}</th>
            <th>{t('import.field.mask')}</th>
          </tr>
        </thead>
        <tbody>
          {(p.sample ?? []).map((r) => (
            <tr key={r.file}>
              <td className="mono" title={r.file}>{r.matched ? null : <Icon spec={codicon('warning')} />} {r.file}</td>
              <td className="mono">{r.case_id}</td>
              <td className="mono">{r.scan_idx}</td>
              <td className="mono">{r.modality ?? '—'}</td>
              <td className="mono" title={r.mask ?? ''}>{r.mask ? <Icon spec={codicon('check')} /> : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {p.unmatched?.length ? (
        <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('import.nifti.unmatched', { count: p.unmatched.length, names: p.unmatched.slice(0, 5).join(', ') })}</p>
      ) : null}
      {p.orphan_masks?.length ? (
        <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('import.nifti.orphans', { count: p.orphan_masks.length })}</p>
      ) : null}
      {Object.keys(p.ignored ?? {}).length ? (
        <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>
          {t('import.ignored', { list: Object.entries(p.ignored ?? {}).map(([ext, n]) => `${n} ${ext}`).join(', ') })}
        </p>
      ) : null}
    </>
  )
}

function Candidates({ cands, value, onPick }: { cands: DetectCandidate[]; value: string | null; onPick: (a: string) => void }) {
  const { t } = useTranslation()
  return (
    <fieldset className="field preset-list" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="field-label">{t('import.adapterTitle')}</legend>
      {cands.map((c) => (
        <label key={c.adapter} className="preset" data-checked={value === c.adapter} aria-disabled={!c.available}>
          <input type="radio" name="adapter" value={c.adapter} disabled={!c.available} checked={value === c.adapter} onChange={() => onPick(c.adapter)} />
          <span>
            <strong>{t(`import.adapter.${c.adapter.replace('.', '_')}`)}</strong>
            <span className="muted">{c.reason}{c.unavailable_reason ? ` — ${c.unavailable_reason}` : ''}</span>
          </span>
          <span className="badge" style={{ marginLeft: 'auto' }}>{t(`import.confidence.${c.confidence}`)}</span>
        </label>
      ))}
    </fieldset>
  )
}

export function ImportWizard() {
  const pid = useImportWizard((s) => s.pid)
  const prefill = useImportWizard((s) => s.prefill)
  return pid ? <Wizard key={pid} pid={pid} prefill={prefill} /> : null
}

const parentOf = (p: string) => p.slice(0, p.lastIndexOf('/')) || '/'

function Wizard({ pid, prefill }: { pid: string; prefill: WizardPrefill | null }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const close = useImportWizard((s) => s.close)
  const [step, setStep] = useState<Step>(prefill ? 'detect' : 'root')
  const [dir, setDir] = useState<string | null>(prefill ? (ACCEPTED.test(prefill.path) ? parentOf(prefill.path) : prefill.path) : null)
  const [file, setFile] = useState<string | null>(prefill && ACCEPTED.test(prefill.path) ? prefill.path : null)
  const [alias, setAlias] = useState('DATA')
  const [upload, setUpload] = useState(false)
  const [files, setFiles] = useState<Partial<Uploads>>({})
  const [adapter, setAdapter] = useState<string | null>(prefill?.adapter ?? null)
  const [options, setOptions] = useState<NiftiOptions>({})
  const [jobId, setJobId] = useState<string | null>(null)
  const [convertError, setConvertError] = useState<unknown>(null)
  const [askDerived, setAskDerived] = useState(false)
  const reviewer = useReviewer((s) => s.name)
  const detect = useDetect()
  const preview = useImportPreview(pid)
  const commit = useCommitImport(pid)
  const job = (useJobs(pid).data ?? []).find((j) => j.job_id === jobId)
  const qc = useQueryClient()
  const p = preview.data
  const path = file ?? dir
  const cands = detect.data?.candidates ?? []

  useEffect(() => {
    if (job?.status === 'succeeded') {
      void qc.invalidateQueries({ queryKey: ['project', pid] })
      void qc.invalidateQueries({ queryKey: ['projects'] })
      const cases = p?.counts.cases
      toast({ message: cases == null ? t('import.converted') : t('import.done', { cases }), tone: 'ok' })
      close()
    }
  }, [job?.status, qc, close, t, p?.counts.cases, pid])

  const pickAdapter = (d: { candidates: DetectCandidate[] }) => {
    const want = prefill?.adapter
    const first = d.candidates.find((c) => c.available && (want ? c.adapter === want : IMPORTABLE.has(c.adapter))) ?? d.candidates.find((c) => c.available)
    setAdapter(first?.adapter ?? null)
  }
  const runDetect = (target: string) => {
    setStep('detect')
    preview.reset()
    detect.mutate(target, { onSuccess: pickAdapter })
  }
  // "Create project from this" (Open mode) arrives with the path: detect at once
  useEffect(() => {
    if (prefill) detect.mutate(prefill.path, { onSuccess: pickAdapter })
    // once per mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const runPreview = (a: ImportAdapter) => {
    if (!path) return
    const req: PreviewRequest = { root: path, alias, adapter: a, add: prefill?.add ?? false }
    if (a === 'nifti-files') req.options = options
    preview.mutate(req, { onSuccess: () => setStep('preview') })
  }

  const i = STEPS.indexOf(step)
  const hasMetadata = p?.files.some((f) => f.kind === 'metadata') ?? false
  const canNext =
    step === 'root'
      ? path !== null && alias !== '' && (!upload || files.metadata != null)
      : step === 'detect'
        ? adapter !== null && !preview.isPending && (adapter === 'open' || adapter === 'dicom.convert' || IMPORTABLE.has(adapter))
        : step === 'preview'
          ? hasMetadata && !commit.isPending
          : false
  const next = async () => {
    if (step === 'root' && path) {
      if (upload && files.metadata) {
        setStep('detect')
        setAdapter('metadata-v1')
        preview.mutate(
          { root: path, alias, files: { metadata: files.metadata, phase: files.phase ?? null, voi_catalog: files.voi_catalog ?? null } },
          { onSuccess: () => setStep('preview') },
        )
      } else runDetect(path)
    } else if (step === 'detect' && adapter) {
      if (adapter === 'open') {
        close()
        navigate(`/open?path=${encodeURIComponent(path ?? '')}`)
      } else if (adapter === 'dicom.convert') void runConvert()
      else runPreview(adapter as ImportAdapter)
    } else if (step === 'preview' && p) {
      const r = await commit.mutateAsync(p.preview_id)
      setJobId(r.job_id)
      setStep('index')
    }
  }
  // DICOM sources go through the converter task (SRC-13, DCM-*); its rows are imported on success
  const runConvert = async () => {
    setConvertError(null)
    try {
      const r = await api.startTaskRun(pid, { task_id: 'dicom.convert', settings: {}, selection: { source: path } }, reviewer || undefined)
      setJobId(r.job_id)
      setStep('index')
    } catch (e) {
      setConvertError(e)
    }
  }
  const failed = job && (job.status === 'failed' || job.status === 'cancelled' || job.status === 'interrupted')
  const onAction = {
    import_as: (a: string | null) => {
      if (!a) return
      setAdapter(a)
      if (IMPORTABLE.has(a)) runPreview(a as ImportAdapter)
    },
    open: () => {
      close()
      navigate(`/open?path=${encodeURIComponent(path ?? '')}`)
    },
    choose_another_path: () => setStep('root'),
    choose_derived_root: () => setAskDerived(true),
  }

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && (step !== 'index' || failed) && close()}
      title={t('import.title')}
      icon={codicon('cloud-download')}
      size="lg"
      footer={
        <>
          <ol className="wiz-steps" aria-label={t('import.steps')}>
            {STEPS.map((s, k) => (
              <li key={s} data-state={k < i ? 'done' : k === i ? 'current' : 'todo'}>
                <span className="wiz-dot">{k < i ? <Icon spec={codicon('check')} /> : k + 1}</span>
                {t(`import.step.${s}`)}
              </li>
            ))}
          </ol>
          <span style={{ flex: 1 }} />
          {step !== 'root' && step !== 'index' ? (
            <button type="button" className="btn" onClick={() => setStep(STEPS[i - 1] ?? 'root')}>{t('common.back')}</button>
          ) : null}
          {step === 'index' && failed ? (
            <button type="button" className="btn" onClick={close}>{t('common.close')}</button>
          ) : null}
          {step !== 'index' ? (
            <button type="button" className="btn btn-primary" disabled={!canNext} onClick={() => void next()}>
              {step === 'preview' ? t('import.commit') : step === 'detect' && adapter === 'open' ? t('import.openInstead') : t('common.next')}
            </button>
          ) : null}
        </>
      }
    >
      {step === 'root' ? (
        <div className="wiz-grid">
          <div>
            <h3>{t('import.rootTitle')}</h3>
            <p className="muted">{t('import.rootHelp')}</p>
            {file ? (
              <p className="mono" style={{ fontSize: 'var(--fs-panel)' }}>
                <Icon spec={codicon('file')} /> {t('import.singleFile', { name: file.slice(file.lastIndexOf('/') + 1) })}
              </p>
            ) : null}
            <label className="field" style={{ marginTop: 12 }}>
              <span className="field-label">{t('import.alias')}</span>
              <input className="input mono" value={alias} onChange={(e) => setAlias(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ''))} />
              <span className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t('import.aliasHelp', { alias })}</span>
            </label>
            <label className="check" style={{ marginTop: 12 }}>
              <input type="checkbox" checked={upload} onChange={(e) => setUpload(e.target.checked)} />
              {t('import.uploadToggle')}
            </label>
            {upload ? <UploadFields files={files} onFiles={setFiles} /> : null}
            <div className="wiz-note">
              <Icon spec={codicon('lock')} />
              {t('import.readOnly')}
            </div>
          </div>
          <FolderBrowser
            path={dir}
            onPath={(d) => {
              setDir(d)
              setFile(null)
            }}
            selected={file}
            onSelectFile={(f) => setFile(file === f ? null : f)}
          />
        </div>
      ) : null}
      {step === 'detect' ? (
        <div>
          <h3>{t('import.detectTitle')}</h3>
          <p className="muted mono">{path}</p>
          {detect.isPending || preview.isPending ? (
            <div className="empty">
              <Icon spec={codicon('loading')} className="codicon-modifier-spin" />
              {t('import.scanning')}
            </div>
          ) : null}
          {detect.isError ? <ProblemCard error={detect.error} onAction={onAction} /> : null}
          {preview.isError ? <ProblemCard error={preview.error} onAction={onAction} /> : null}
          {convertError ? <ProblemCard error={convertError} onAction={onAction} /> : null}
          {askDerived ? (
            <DerivedRootDialog
              pid={pid}
              onClose={(ok) => {
                setAskDerived(false)
                if (ok) void runConvert()
              }}
            />
          ) : null}
          {cands.length ? (
            <div className="wiz-grid" style={{ marginTop: 8 }}>
              <Candidates cands={cands} value={adapter} onPick={setAdapter} />
              <div>
                {adapter === 'nifti-files' ? <NiftiOptionsForm value={options} onChange={setOptions} /> : null}
                {detect.data && Object.keys(detect.data.ignored).length ? (
                  <p className="muted" style={{ fontSize: 'var(--fs-panel)', marginTop: 8 }}>
                    {t('import.ignored', { list: Object.entries(detect.data.ignored).map(([ext, n]) => `${n} ${ext}`).join(', ') })}
                  </p>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
      {step === 'preview' && p ? (
        <div className="wiz-grid">
          <div>
            <h3>{t('import.previewTitle')}</h3>
            <div className="stat-grid" style={{ gridTemplateColumns: 'repeat(2, 1fr)', marginTop: 0 }}>
              <div className="card"><span className="kpi num">{p.counts.scan_rows}</span><span className="muted">{t('import.kpiRows')}</span></div>
              <div className="card"><span className="kpi num">{p.counts.cases}</span><span className="muted">{t('import.kpiCases')}</span></div>
              <div className="card"><span className="kpi num">{p.counts.voi_rows}</span><span className="muted">{t('import.kpiVoi')}</span></div>
              <div className="card"><span className="kpi num">{p.counts.excluded_upstream}</span><span className="muted">{t('import.kpiExcluded')}</span></div>
            </div>
            {p.adapter === 'nifti-files' ? null : (
              <>
                <h3 style={{ marginTop: 16 }}>{t('import.mapping')}</h3>
                <Mapping preview={p} />
                <table className="table" style={{ marginTop: 12 }}>
                  <tbody>
                    {p.files.map((f) => (
                      <tr key={f.kind}>
                        <td style={{ color: 'var(--ok)' }}><Icon spec={codicon('pass')} /></td>
                        <td className="mono">{f.name}</td>
                        <td className="muted">{t(`import.source.${f.source}`)}</td>
                        <td className="num muted">{t('import.rows', { count: f.rows })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
          <div>
            {p.adapter === 'nifti-files' ? (
              <>
                <h3>{t('import.nifti.sampleTitle')}</h3>
                <NiftiSample p={p} />
              </>
            ) : null}
            <h3>{t('import.errors', { count: p.n_errors })}</h3>
            <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('import.errorsHelp')}</p>
            {p.n_errors > MAX_ERRORS ? <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('import.errorsFirst', { n: MAX_ERRORS })}</p> : null}
            <table className="table">
              <tbody>
                {p.errors.slice(0, MAX_ERRORS).map((e, k) => (
                  <tr key={k}>
                    <td style={{ color: 'var(--error)' }}><Icon spec={codicon('error')} /></td>
                    <td className="num muted mono">{e.line != null ? t('import.fileLine', { file: e.file, n: e.line }) : e.file}</td>
                    <td className="mono">{e.field ?? ''}</td>
                    <td style={{ whiteSpace: 'normal' }}>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
      {step === 'index' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '24px 0' }}>
          <h3>{t(failed ? 'import.indexFailed' : 'import.indexing')}</h3>
          {failed ? (
            <div className="error-card" role="alert">{job.error ?? t(`jobs.status.${job.status}`)}</div>
          ) : (
            <>
              <Progress value={job?.done ?? 0} total={job?.total || 1} />
              <span className="muted num">{t('jobs.count', { done: job?.done ?? 0, total: job?.total ?? 0 })}</span>
            </>
          )}
          <span className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('import.indexingHelp')}</span>
        </div>
      ) : null}
    </Dialog>
  )
}
