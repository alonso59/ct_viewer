// Import wizard (IMP-01..05): data root → detected files → preview → commit + indexing job.
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { create } from 'zustand'

import { useCommitImport, useFsList, useImportPreview, useJobs } from '../../api'
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

function FolderBrowser({ path, onPath }: { path: string; onPath: (p: string) => void }) {
  const { t } = useTranslation()
  const { data, isLoading } = useFsList(path)
  const parent = path === '/' ? null : path.slice(0, path.lastIndexOf('/')) || '/'
  return (
    <div className="fs">
      <div className="fs-path mono">
        <Icon spec={codicon('folder-opened')} />
        {path}
      </div>
      <div className="fs-list" role="listbox" aria-label={t('import.folders')}>
        {parent ? (
          <button type="button" className="list-row" onClick={() => onPath(parent)}>
            <Icon spec={codicon('arrow-up')} />
            {t('import.up')}
          </button>
        ) : null}
        {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
        {data?.map((e) => (
          <button key={e.path} type="button" className="list-row" disabled={e.kind === 'file'} onClick={() => onPath(e.path)}>
            <Icon spec={codicon(e.kind === 'dir' ? 'folder' : 'file')} />
            <span>{e.name}</span>
            {e.detected?.length ? <span className="badge" data-tone="ok" style={{ marginLeft: 'auto' }}>{t('import.detectedCount', { count: e.detected.length })}</span> : null}
          </button>
        ))}
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t('import.allowedRoots')}</div>
    </div>
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
  const [path, setPath] = useState('/data')
  const [root, setRoot] = useState<string | null>(null)
  const [alias, setAlias] = useState('DATA')
  const [jobId, setJobId] = useState<string | null>(null)
  const preview = useImportPreview(pid, root)
  const commit = useCommitImport(pid)
  const job = (useJobs().data ?? []).find((j) => j.job_id === jobId)
  const qc = useQueryClient()

  useEffect(() => {
    if (job?.status === 'completed') {
      void qc.invalidateQueries()
      toast({ message: t('import.done', { items: preview.data?.n_items ?? 0 }), tone: 'ok' })
      close()
    }
  }, [job?.status, qc, close, t, preview.data?.n_items])

  const i = STEPS.indexOf(step)
  const canNext = step === 'root' ? path.split('/').length > 2 : step === 'detect' ? !!preview.data : step === 'preview'
  const next = async () => {
    if (step === 'root') {
      setRoot(path)
      setStep('detect')
    } else if (step === 'detect') setStep('preview')
    else if (step === 'preview') {
      const r = await commit.mutateAsync()
      setJobId(r.job_id)
      setStep('index')
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && step !== 'index' && close()}
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
          {step !== 'index' ? (
            <button type="button" className="btn btn-primary" disabled={!canNext || commit.isPending} onClick={() => void next()}>
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
          <p className="muted mono">{root}</p>
          {preview.isLoading ? (
            <div className="empty">
              <Icon spec={codicon('loading')} className="codicon-modifier-spin" />
              {t('import.scanning')}
            </div>
          ) : (
            <table className="table" style={{ maxWidth: 560 }}>
              <tbody>
                {preview.data?.detected.map((d) => (
                  <tr key={d.file}>
                    <td style={{ color: d.found ? 'var(--ok)' : 'var(--fg-muted)' }}><Icon spec={codicon(d.found ? 'pass' : 'circle-large-outline')} /></td>
                    <td className="mono">{d.file}</td>
                    <td className="num muted">{t('import.rows', { count: d.rows })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('import.uploadAlt')}</p>
        </div>
      ) : null}
      {step === 'preview' && preview.data ? (
        <div className="wiz-grid">
          <div>
            <h3>{t('import.previewTitle')}</h3>
            <div className="stat-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', marginTop: 0 }}>
              <div className="card"><span className="kpi num">{preview.data.n_rows}</span><span className="muted">{t('import.kpiRows')}</span></div>
              <div className="card"><span className="kpi num">{preview.data.n_cases}</span><span className="muted">{t('import.kpiCases')}</span></div>
              <div className="card"><span className="kpi num">{preview.data.n_items}</span><span className="muted">{t('import.kpiItems')}</span></div>
            </div>
            <h3 style={{ marginTop: 16 }}>{t('import.mapping')}</h3>
            <table className="table">
              <tbody>
                {preview.data.mapping.map((m) => (
                  <tr key={m.field}>
                    <td>{m.field}</td>
                    <td className="muted"><Icon spec={codicon('arrow-left')} /></td>
                    <td className="mono">{m.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <h3>{t('import.errors', { count: preview.data.errors.length })}</h3>
            <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('import.errorsHelp')}</p>
            <table className="table">
              <tbody>
                {preview.data.errors.map((e) => (
                  <tr key={`${e.row}-${e.code}`}>
                    <td style={{ color: 'var(--error)' }}><Icon spec={codicon('error')} /></td>
                    <td className="num muted">{t('import.row', { n: e.row })}</td>
                    <td className="mono">{e.code}</td>
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
          <h3>{t('import.indexing')}</h3>
          <Progress value={job?.done ?? 0} total={job?.total ?? 1} />
          <span className="muted num">{t('jobs.count', { done: job?.done ?? 0, total: job?.total ?? 0 })}</span>
          <span className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('import.indexingHelp')}</span>
        </div>
      ) : null}
    </Dialog>
  )
}
