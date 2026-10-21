// Converter overlay window (UI-25, DCM-14, TSK-13): source → settings → dry run → run → result.
// Without a project the output is a write-once workspace dataset (`{derived}/_datasets/{name}/`)
// with Open / Create project / Add to project; inside a project it can convert into it instead.
// A click outside never closes it; while it works, × and Escape minimize it to a chip that
// shows the progress, and the work goes on (the dry run and the run are server-side).
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import {
  api,
  useEstimateProgress,
  useProject,
  useProjects,
  useTaskRun,
  useTasks,
  useWorkspaceRun,
  useWorkspaceRuns,
  type EstimateProgress,
  type TaskEstimate,
} from '../../api'
import { DerivedRootDialog, FolderBrowser, useImportWizard } from '../../features/import'
import { NewProjectDialog } from '../../features/import'
import { Dialog, fmtBytes, openPath, ProblemCard, Progress } from '../../lib'
import { Icon, codicon } from '../../theme'
import { datasetSlug, defaultDatasetName, STEPS, useConverter, type Draft, type Scan, type Step } from './store'
import './converter.css'

const ACTIVE = ['queued', 'running', 'waiting_for_runner']
/** The dry run's stages in order (`pipeline.Stage`); `check` = the source is searched for DICOM */
const SCAN_STAGES = ['check', 'listing', 'reading', 'planning'] as const

/** Names a dry run (`progress_id`); `crypto.randomUUID` needs a secure context, a LAN http URL isn't */
const scanId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

/** What the window is doing, for its progress panel and its minimized chip */
interface Activity {
  label: string
  done: number
  total: number
  finished: boolean
  tone?: 'ok' | 'warn' | 'error'
}

function StepBar({ step }: { step: Step }) {
  const { t } = useTranslation()
  return (
    <ol className="conv-steps" aria-label={t('conv.steps')}>
      {STEPS.map((s, i) => (
        <li key={s} aria-current={s === step ? 'step' : undefined} data-done={STEPS.indexOf(step) > i}>
          {t(`conv.step.${s}`)}
        </li>
      ))}
    </ol>
  )
}

/** DCM-06 (AUD-A2-13): every series of the dry run, what happens to it and why, with its size */
function SeriesPlanTable({ estimate }: { estimate: TaskEstimate }) {
  const { t } = useTranslation()
  const rows = estimate.series ?? []
  const skipped = rows.filter((r) => r.action === 'skip').length
  if (!rows.length) return null
  return (
    <details className="conv-plan" open={skipped > 0 && rows.length <= 20}>
      <summary>{t('conv.plan', { count: rows.length, skipped })}</summary>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>{t('conv.planCase')}</th>
              <th>{t('conv.planPatient')}</th>
              <th>{t('conv.planSeries')}</th>
              <th className="num">{t('conv.planFiles')}</th>
              <th>{t('conv.planAction')}</th>
              <th className="num">{t('conv.planSize')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.case_id}.${r.scan_idx}`} data-action={r.action}>
                <td className="mono">{t('conv.planId', { case: r.case_id, scan: r.scan_idx })}</td>
                <td className="mono">{r.patient || '—'}</td>
                <td>{r.description || '—'}{r.modality ? <span className="muted">{t('conv.planModality', { modality: r.modality })}</span> : null}</td>
                <td className="num">{r.n_files}</td>
                <td>{r.action === 'convert' ? t('conv.actionConvert') : t('conv.actionSkip', { reason: t(`conv.reason.${r.reason}`, { defaultValue: r.reason || '—' }) })}</td>
                <td className="num">{r.action === 'convert' ? fmtBytes(r.bytes) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {estimate.series_truncated ? <p className="muted conv-help">{t('conv.planTruncated', { n: rows.length })}</p> : null}
    </details>
  )
}

/** Seconds since `since`, updated every second */
function useElapsed(since: number | null) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (since == null) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [since])
  return since == null ? 0 : Math.max(0, Math.round((now - since) / 1000))
}

/** DCM-06: the dry run's stages, where it is and how far, so a long scan is visibly alive */
function ScanPanel({ progress, elapsed, onCancel, onMinimize }: { progress: EstimateProgress | undefined; elapsed: number; onCancel: () => void; onMinimize: () => void }) {
  const { t } = useTranslation()
  const current = progress?.stage ?? 'check'
  const at = Math.max(0, SCAN_STAGES.indexOf(current as (typeof SCAN_STAGES)[number]))
  const determinate = (current === 'reading' || current === 'planning') && !!progress?.total
  return (
    <div className="conv-scan" data-testid="conv-scan" role="status" aria-live="polite">
      <ol className="conv-stages">
        {SCAN_STAGES.map((s, i) => (
          <li key={s} data-state={i < at ? 'done' : i === at ? 'current' : 'pending'}>
            <Icon spec={codicon(i < at ? 'pass' : i === at ? 'loading' : 'circle-large')} className={i === at ? 'codicon-modifier-spin' : undefined} />
            <span>{t(`conv.stage.${s}`, { done: progress?.done ?? 0, total: progress?.total ?? 0 })}</span>
          </li>
        ))}
      </ol>
      {determinate && progress ? <Progress value={progress.done} total={progress.total} /> : <div className="progress conv-indeterminate"><span /></div>}
      <div className="conv-row">
        <span className="muted conv-help">{t('conv.elapsed', { s: elapsed })}</span>
        <span style={{ flex: 1 }} />
        <button type="button" className="btn btn-sm" onClick={onMinimize}>{t('conv.minimize')}</button>
        <button type="button" className="btn btn-sm" onClick={onCancel}>{t('conv.cancelScan')}</button>
      </div>
    </div>
  )
}

function RunPanel({ activity, onResult, onCancel }: { activity: Activity; onResult: () => void; onCancel: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="conv-body" role="status" aria-live="polite">
      {activity.total > 0 ? <Progress value={activity.done} total={activity.total} /> : <div className="progress conv-indeterminate"><span /></div>}
      <p className="muted">{activity.label}</p>
      <div className="conv-row conv-actions">
        {activity.finished ? (
          <button type="button" className="btn btn-primary" onClick={onResult}>{t('conv.showResult')}</button>
        ) : (
          <button type="button" className="btn" onClick={onCancel}>{t('conv.cancelRun')}</button>
        )}
      </div>
    </div>
  )
}

/** The minimized window: a notification-like chip with the progress and Show (UI-25) */
function ConverterChip({ activity, onShow, onClose }: { activity: Activity | null; onShow: () => void; onClose: () => void }) {
  const { t } = useTranslation()
  const running = !!activity && !activity.finished
  const icon = running ? 'sync' : activity?.tone === 'error' ? 'error' : activity?.tone === 'warn' ? 'warning' : activity ? 'pass' : 'file-binary'
  return (
    <div className="overlay conv-chip" role="status" aria-live="polite" data-testid="conv-chip">
      <span style={{ color: `var(--${activity?.tone ?? 'accent'})`, display: 'inline-flex' }}>
        <Icon spec={codicon(icon)} className={running ? 'codicon-modifier-spin' : undefined} />
      </span>
      <div className="conv-chip-text">
        <strong>{t('conv.title')}</strong>
        <span className="muted">{activity?.label ?? t('conv.idle')}</span>
        {running ? activity.total > 0 ? <Progress value={activity.done} total={activity.total} /> : <div className="progress conv-indeterminate"><span /></div> : null}
      </div>
      <button type="button" className="btn btn-sm" onClick={onShow}>{t('conv.show')}</button>
      {running ? null : (
        <button type="button" className="icon-btn" aria-label={t('conv.close')} onClick={onClose}>
          <Icon spec={codicon('close')} />
        </button>
      )}
    </div>
  )
}

export default function ConverterOverlay() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const c = useConverter()
  const { pid, close, createFrom, patch, step, source, browse, target, settings, estimate, error, scan, run, minimized } = c
  const project = useProject(pid ?? '').data
  const manifest = useTasks().data?.tasks.find((x) => x.manifest.id === 'dicom.convert')?.manifest
  const profiles = ((manifest?.settings_schema?.properties as Record<string, { enum?: string[] }> | undefined)?.target_profile?.enum ?? ['generic']) as string[]
  const [creating, setCreating] = useState(false)
  const [derivedPrompt, setDerivedPrompt] = useState(false)
  const [addTo, setAddTo] = useState('')
  const [busy, setBusy] = useState(false)
  const projects = useProjects().data ?? []
  const datasets = useWorkspaceRuns().data ?? []
  const slug = datasetSlug(settings.name.trim() || defaultDatasetName())
  const taken = new Set(datasets.map((r) => r.name))
  const clash = target === 'dataset' && taken.has(slug) ? { name: slug } : null
  let nextFree = slug
  for (let n = 1; taken.has(nextFree); n++) nextFree = `${slug}-${n}`
  const ws = useWorkspaceRun(run?.kind === 'dataset' ? run.rid : null).data
  const prun = useTaskRun(pid ?? '', run?.kind === 'project' ? run.rid : null).data
  const intoProject = target === 'project' && !!pid
  const needsDerived = intoProject && !!project && !project.path_roots.some((r) => r.role === 'derived')
  const taskSettings = { target_profile: settings.target_profile, phase_analyzer: settings.phase_analyzer, anonymize: settings.anonymize }
  const setSettings = (s: Partial<Draft['settings']>) => patch({ settings: { ...settings, ...s } })
  const scanProgress = useEstimateProgress(scan?.id ?? null).data
  const elapsed = useElapsed(scan?.started ?? null)

  // What is going on, for the run panel and the chip
  const runStatus = run?.kind === 'dataset' ? ws?.status : prun?.status
  const runFinished = !!runStatus && !ACTIVE.includes(runStatus)
  let activity: Activity | null = null
  if (scan) {
    const s = scanProgress?.stage ?? 'check'
    activity = { label: `${t('conv.dryRunning')} · ${t(`conv.stage.${s}`, { done: scanProgress?.done ?? 0, total: scanProgress?.total ?? 0 })}`, done: scanProgress?.done ?? 0, total: s === 'reading' || s === 'planning' ? scanProgress?.total ?? 0 : 0, finished: false }
  } else if (run) {
    const p = (run.kind === 'dataset' ? ws?.progress : prun?.progress) as Record<string, number | string | null | undefined> | undefined
    const done = Number(p?.done ?? 0)
    const total = Number(p?.total ?? 0)
    if (runFinished) {
      const tone = runStatus === 'completed' ? 'ok' : runStatus === 'completed_with_errors' ? 'warn' : 'error'
      activity = { label: t(`conv.status.${runStatus}`, { defaultValue: runStatus }), done, total, finished: true, tone }
    } else if (total === 0 && p?.stage) {
      // still scanning headers: the run reports the same stages as the dry run
      const sd = Number(p.stage_done ?? 0)
      const st = Number(p.stage_total ?? 0)
      activity = { label: `${t('conv.status.running')} · ${t(`conv.stage.${String(p.stage)}`, { done: sd, total: st })}`, done: sd, total: p.stage === 'reading' ? st : 0, finished: false }
    } else {
      activity = { label: total ? t('conv.converting', { done, total }) : t('conv.status.running'), done, total, finished: false }
    }
  } else if (estimate && step === 'estimate') {
    activity = { label: t('conv.dryRunDone', { n: estimate.n_units }), done: 1, total: 1, finished: true, tone: 'ok' }
  }
  const working = !!scan || (!!run && !runFinished)
  useEffect(() => {
    useConverter.setState({ working })
  }, [working])

  const guard = async (fn: () => Promise<void>) => {
    patch({ error: null })
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      patch({ error: e })
    } finally {
      setBusy(false)
    }
  }
  // Writes to the store, not to this component: the result lands even if the window was
  // minimized or remounted meanwhile; a cancelled dry run's answer is dropped
  const dryRun = async () => {
    if (!source) return
    const me: Scan = { id: scanId(), started: Date.now() }
    patch({ error: null, scan: me })
    const sel = { source }
    try {
      const est = intoProject && pid ? await api.estimateTask(pid, 'dicom.convert', sel, taskSettings, me.id) : await api.estimateWorkspaceTask('dicom.convert', sel, taskSettings, me.id)
      if (useConverter.getState().scan?.id === me.id) patch({ estimate: est, step: 'estimate', scan: null })
    } catch (e) {
      if (useConverter.getState().scan?.id === me.id) patch({ error: e, scan: null })
    }
  }
  const cancelScan = () => {
    if (!scan) return
    void api.cancelEstimate(scan.id).catch(() => undefined)
    patch({ scan: null })
  }
  const start = () =>
    guard(async () => {
      if (!source) return
      const selection = { source }
      if (intoProject && pid) {
        const r = await api.startTaskRun(pid, { task_id: 'dicom.convert', settings: taskSettings, selection })
        patch({ run: { kind: 'project', rid: r.run_id }, step: 'run' })
      } else {
        const r = await api.startWorkspaceRun({ task_id: 'dicom.convert', settings: taskSettings, selection, name: settings.name.trim() || null })
        patch({ run: { kind: 'dataset', rid: r.run_id }, step: 'run' })
      }
    })
  const cancelRun = () =>
    guard(async () => {
      if (!run) return
      if (run.kind === 'project' && pid) await api.cancelTaskRun(pid, run.rid)
      else await api.cancelWorkspaceRun(run.rid)
    })
  // × and Escape: minimize while working (nothing is lost), close otherwise
  const onOpenChange = (o: boolean) => {
    if (o) return
    if (working) c.minimize()
    else close()
  }
  const dataset = ws?.dataset_dir ?? ''
  const openDataset = () => {
    close()
    openPath(navigate, dataset)
  }
  const addToProject = () => {
    if (!addTo) return
    close()
    navigate(`/p/${addTo}`)
    useImportWizard.getState().open(addTo, { path: dataset, add: true })
  }

  return (
    <>
      {minimized ? <ConverterChip activity={activity} onShow={c.restore} onClose={close} /> : null}
      <Dialog
        open={!minimized}
        onOpenChange={onOpenChange}
        title={t('conv.title')}
        icon={codicon('file-binary')}
        size="lg"
        dismissible={false}
        actions={
          <button type="button" className="icon-btn" aria-label={t('conv.minimize')} title={t('conv.minimizeHint')} onClick={c.minimize}>
            <Icon spec={codicon('chrome-minimize')} />
          </button>
        }
      >
        <div className="conv">
          <StepBar step={step} />
          {step === 'source' ? (
            <div className="conv-body">
              <p className="muted">{t('conv.sourceHelp')}</p>
              <FolderBrowser path={browse} onPath={(p) => patch({ browse: p, source: p })} selected={source} onSelectFile={(p) => patch({ source: p })} />
              <div className="conv-row">
                <span className="mono conv-path">{source ?? t('conv.noSource')}</span>
                <button type="button" className="btn btn-primary" disabled={!source} onClick={() => patch({ step: 'settings', settings: { ...settings, name: settings.name || defaultDatasetName() } })}>{t('conv.next')}</button>
              </div>
            </div>
          ) : null}
          {step === 'settings' ? (
            <div className="conv-body">
              <div className="conv-row"><span className="muted">{t('conv.source')}</span><span className="mono conv-path">{source}</span><button type="button" className="btn btn-sm" disabled={!!scan} onClick={() => patch({ step: 'source' })}>{t('conv.change')}</button></div>
              <fieldset className="conv-fields" disabled={!!scan}>
                {pid ? (
                  <div className="field">
                    <span className="field-label">{t('conv.output')}</span>
                    <div className="seg" role="group">
                      <button type="button" aria-pressed={target === 'project'} onClick={() => patch({ target: 'project' })}>{t('conv.intoProject', { name: project?.name ?? '' })}</button>
                      <button type="button" aria-pressed={target === 'dataset'} onClick={() => patch({ target: 'dataset' })}>{t('conv.asDataset')}</button>
                    </div>
                  </div>
                ) : null}
                {target === 'dataset' ? (
                  <label className="field">
                    <span className="field-label">{t('conv.name')}</span>
                    <input className="input" value={settings.name} onChange={(e) => setSettings({ name: e.target.value })} />
                    {/* DCM-14 (AUD-A2-14): a taken name is said here, not silently suffixed later */}
                    {clash ? <span className="conv-help" role="note" style={{ color: 'var(--warn)' }}>{t('conv.nameTaken', { name: clash.name, next: nextFree })}</span> : null}
                    <span className="muted conv-help">{t('conv.nameHelp')}</span>
                  </label>
                ) : null}
                <label className="field">
                  <span className="field-label">{t('conv.profile')}</span>
                  <select className="input" value={settings.target_profile} onChange={(e) => setSettings({ target_profile: e.target.value })}>
                    {profiles.map((p) => <option key={p} value={p}>{t(`conv.profiles.${p}`, { defaultValue: p })}</option>)}
                  </select>
                  <span className="muted conv-help">{t('conv.profileHelp')}</span>
                </label>
                <label className="conv-check">
                  <input type="checkbox" checked={settings.phase_analyzer} onChange={(e) => setSettings({ phase_analyzer: e.target.checked })} />
                  {t('conv.phase')}
                </label>
                <label className="conv-check">
                  <input type="checkbox" checked={settings.anonymize === 'basic'} onChange={(e) => setSettings({ anonymize: e.target.checked ? 'basic' : 'none' })} />
                  {t('conv.anonymize')}
                </label>
              </fieldset>
              <p className="muted conv-help">{t('conv.phiNotice')}</p>
              {needsDerived ? (
                <div className="error-card">
                  {t('conv.needsDerived')} <button type="button" className="btn btn-sm" onClick={() => setDerivedPrompt(true)}>{t('conv.chooseDerived')}</button>
                </div>
              ) : null}
              {scan ? (
                <ScanPanel progress={scanProgress} elapsed={elapsed} onCancel={cancelScan} onMinimize={c.minimize} />
              ) : (
                <div className="conv-row conv-actions">
                  <button type="button" className="btn btn-primary" disabled={needsDerived} onClick={() => void dryRun()}>{t('conv.dryRun')}</button>
                  <span className="muted conv-help">{t('conv.dryRunHelp')}</span>
                </div>
              )}
            </div>
          ) : null}
          {step === 'estimate' && estimate ? (
            <div className="conv-body">
              <div className="stat-grid">
                <div className="card"><span className="kpi num">{String(estimate.detail?.series ?? estimate.n_units + estimate.n_skipped)}</span><span className="muted">{t('conv.found')}</span></div>
                <div className="card"><span className="kpi num">{estimate.n_units}</span><span className="muted">{t('conv.selected')}</span></div>
                <div className="card"><span className="kpi num">{estimate.n_skipped}</span><span className="muted">{t('conv.skipped')}</span></div>
                <div className="card"><span className="kpi num">{fmtBytes(estimate.output_bytes)}</span><span className="muted">{t('conv.storage')}</span></div>
              </div>
              <SeriesPlanTable estimate={estimate} />
              {estimate.sample_errors?.length ? <div className="error-card">{estimate.sample_errors.join('; ')}</div> : null}
              <div className="conv-row conv-actions">
                <button type="button" className="btn" onClick={() => patch({ step: 'settings' })}>{t('conv.back')}</button>
                <button type="button" className="btn btn-primary" disabled={busy || estimate.n_units === 0} onClick={() => void start()}>{t('conv.run', { n: estimate.n_units })}</button>
              </div>
            </div>
          ) : null}
          {step === 'run' && activity ? <RunPanel activity={activity} onResult={() => patch({ step: 'result' })} onCancel={() => void cancelRun()} /> : null}
          {step === 'run' && (ws?.error || prun?.error) ? <div className="error-card">{ws?.error ?? prun?.error}</div> : null}
          {step === 'result' && run?.kind === 'dataset' && ws ? (
            <div className="conv-body" data-testid="conv-result">
              <p>{t(ws.status === 'completed' ? 'conv.datasetReady' : 'conv.datasetPartial', { name: ws.name })}</p>
              <p className="mono conv-path">{dataset}</p>
              <p className="muted conv-help">{t('conv.datasetHelp')}</p>
              <div className="conv-row conv-actions">
                <button type="button" className="btn" onClick={openDataset}>{t('conv.open')}</button>
                <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>{t('conv.createProject')}</button>
              </div>
              <div className="conv-row">
                <select className="input" aria-label={t('conv.addTo')} value={addTo} onChange={(e) => setAddTo(e.target.value)}>
                  <option value="">{t('conv.pickProject')}</option>
                  {projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}
                </select>
                <button type="button" className="btn" disabled={!addTo} onClick={addToProject}>{t('conv.addTo')}</button>
              </div>
              <NewProjectDialog open={creating} onOpenChange={(o) => { setCreating(o); if (!o) close() }} prefill={{ path: dataset }} />
            </div>
          ) : null}
          {step === 'result' && run?.kind === 'project' ? (
            <div className="conv-body">
              <p>{t('conv.projectDone')}</p>
              <div className="conv-row conv-actions"><button type="button" className="btn btn-primary" onClick={close}>{t('conv.close')}</button></div>
            </div>
          ) : null}
          {error ? (
            <ProblemCard
              error={error}
              labels={{ import_as: t('conv.createProject') }}
              onAction={{
                // AUD-A2-07: no DICOM here → view it, or make a project from its NIfTI files
                open: () => {
                  close()
                  if (source) openPath(navigate, source)
                },
                import_as: () => source && useConverter.setState({ createFrom: source }),
                choose_another_path: () => patch({ error: null, step: 'source' }),
              }}
            />
          ) : null}
        </div>
      </Dialog>
      {createFrom ? <NewProjectDialog open onOpenChange={(o) => { if (!o) { useConverter.setState({ createFrom: null }); close() } }} prefill={{ path: createFrom, adapter: 'nifti-files' }} /> : null}
      {derivedPrompt && pid ? <DerivedRootDialog pid={pid} onClose={() => setDerivedPrompt(false)} /> : null}
    </>
  )
}
