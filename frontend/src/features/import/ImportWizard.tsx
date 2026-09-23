// Import wizard (IMP-01..05): data root (server folder browser, API-10) → detected or uploaded
// input files (API-11) → preview → commit (API-12) + indexing job (SSE progress, API-40).
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { create } from 'zustand'

import { useCommitImport, useFsList, useImportPreview, useJobs, type ImportPreview, type PreviewRequest } from '../../api'
import { Dialog, Progress } from '../../lib'
import { toast } from '../../shell'
import { Icon, codicon } from '../../theme'
import './import.css'

interface WizardState {
  pid: string | null
  open: (pid: string) => void
  close: () => void
}
export const useImportWizard = create<WizardState>()((set) => ({
  pid: null,
  open: (pid) => set({ pid }),
  close: () => set({ pid: null }),
}))

const STEPS = ['root', 'detect', 'preview', 'index'] as const
type Step = (typeof STEPS)[number]
const MAX_ERRORS = 50

/** IMP-01: browse folders under ALLOWED_DATA_ROOTS; `null` lists the allowed roots themselves */
function FolderBrowser({ path, onPath }: { path: string | null; onPath: (p: string | null) => void }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, error } = useFsList(path)
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
        {isError ? <div className="error-card">{error.message}</div> : null}
        {data && data.entries.length === 0 ? <div className="empty">{t(path === null ? 'import.noRoots' : 'import.emptyFolder')}</div> : null}
        {data?.entries.map((e) => (
          <button key={e.path} type="button" className="list-row" disabled={e.kind === 'file'} onClick={() => onPath(e.path)} title={e.path}>
            <Icon spec={codicon(e.kind === 'dir' ? 'folder' : 'file')} />
            <span>{e.name}</span>
            {e.has_metadata ? <span className="badge" data-tone="ok" style={{ marginLeft: 'auto' }}>{t('import.hasMetadata')}</span> : null}
          </button>
        ))}
        {data?.truncated ? <div className="muted" style={{ padding: '4px 12px' }}>{t('import.truncated')}</div> : null}
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t('import.allowedRoots')}</div>
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

export function ImportWizard() {
  const pid = useImportWizard((s) => s.pid)
  return pid ? <Wizard key={pid} pid={pid} /> : null
}

function Wizard({ pid }: { pid: string }) {
  const { t } = useTranslation()
  const close = useImportWizard((s) => s.close)
  const [step, setStep] = useState<Step>('root')
  const [path, setPath] = useState<string | null>(null)
  const [alias, setAlias] = useState('DATA')
  const [upload, setUpload] = useState(false)
  const [files, setFiles] = useState<Partial<Uploads>>({})
  const [jobId, setJobId] = useState<string | null>(null)
  const preview = useImportPreview(pid)
  const commit = useCommitImport(pid)
  const job = (useJobs(pid).data ?? []).find((j) => j.job_id === jobId)
  const qc = useQueryClient()
  const p = preview.data

  useEffect(() => {
    if (job?.status === 'succeeded') {
      void qc.invalidateQueries({ queryKey: ['project', pid] })
      void qc.invalidateQueries({ queryKey: ['projects'] })
      toast({ message: t('import.done', { cases: p?.counts.cases ?? 0 }), tone: 'ok' })
      close()
    }
  }, [job?.status, qc, close, t, p?.counts.cases, pid])

  const i = STEPS.indexOf(step)
  const hasMetadata = p?.files.some((f) => f.kind === 'metadata') ?? false
  const canNext =
    step === 'root'
      ? path !== null && alias !== '' && (!upload || files.metadata != null)
      : step === 'detect'
        ? hasMetadata
        : step === 'preview'
          ? hasMetadata && !commit.isPending
          : false
  const next = async () => {
    if (step === 'root' && path) {
      setStep('detect')
      const req: PreviewRequest = { root: path, alias }
      if (upload && files.metadata) req.files = { metadata: files.metadata, phase: files.phase ?? null, voi_catalog: files.voi_catalog ?? null }
      preview.mutate(req)
    } else if (step === 'detect') setStep('preview')
    else if (step === 'preview' && p) {
      const r = await commit.mutateAsync(p.preview_id)
      setJobId(r.job_id)
      setStep('index')
    }
  }
  const failed = job && (job.status === 'failed' || job.status === 'cancelled' || job.status === 'interrupted')

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
              {step === 'preview' ? t('import.commit') : t('common.next')}
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
          <FolderBrowser path={path} onPath={setPath} />
        </div>
      ) : null}
      {step === 'detect' ? (
        <div>
          <h3>{t('import.detectTitle')}</h3>
          <p className="muted mono">{path}</p>
          {preview.isPending ? (
            <div className="empty">
              <Icon spec={codicon('loading')} className="codicon-modifier-spin" />
              {t('import.scanning')}
            </div>
          ) : null}
          {preview.isError ? (
            <div className="error-card" role="alert">
              <strong>{preview.error.message}</strong>
            </div>
          ) : null}
          {p ? (
            <>
              <table className="table" style={{ maxWidth: 560 }}>
                <tbody>
                  {(['metadata', 'phase', 'voi_catalog'] as const).map((kind) => {
                    const f = p.files.find((x) => x.kind === kind)
                    return (
                      <tr key={kind}>
                        <td style={{ color: f ? 'var(--ok)' : 'var(--fg-muted)' }}><Icon spec={codicon(f ? 'pass' : 'circle-large-outline')} /></td>
                        <td className="mono">{f?.name ?? t(`import.file.${kind}`)}</td>
                        <td className="muted">{f ? t(`import.source.${f.source}`) : t('import.notFound')}</td>
                        <td className="num muted">{f ? t('import.rows', { count: f.rows }) : ''}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {!hasMetadata ? <div className="error-card">{t('import.noMetadata')}</div> : null}
            </>
          ) : null}
          <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('import.uploadAlt')}</p>
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
            <h3 style={{ marginTop: 16 }}>{t('import.mapping')}</h3>
            <Mapping preview={p} />
          </div>
          <div>
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
