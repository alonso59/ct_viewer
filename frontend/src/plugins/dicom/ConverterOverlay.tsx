// Converter overlay window (UI-25, DCM-14, TSK-13): source → settings → dry run → run → result.
// Without a project the output is a write-once workspace dataset (`{derived}/_datasets/{name}/`)
// with Open / Create project / Add to project; inside a project it can convert into it instead.
// A click outside never closes it; while it works, × and Escape minimize it to a chip that
// shows the progress, and the work goes on (the dry run and the run are server-side).
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import {
  api,
  useEstimateProgress,
  useProject,
  useProjects,
  useTaskRun,
  useTasks,
  isTaskRunPending,
  useWorkspaceRun,
  useWorkspaceRuns,
  useSourceOperation,
  useSourceOperations,
  useSourcePlan,
  keys,
  type SourceOperation,
  type EstimateProgress,
  type TaskEstimate,
} from '../../api'
import { DerivedRootDialog, FolderBrowser, useImportWizard } from '../../features/import'
import { ProblemError, toProblemError } from '../../api/problem'
import { NewProjectDialog } from '../../features/import'
import { Dialog, fmtBytes, openPath, ProblemCard, Progress } from '../../lib'
import { Icon, codicon } from '../../theme'
import { datasetSlug, defaultDatasetName, STEPS, useConverter, type Draft, type Step } from './store'
import { PhasePanel } from './PhasePanel'
import './converter.css'

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
function SeriesPlanTable({ estimate, operation }: { estimate: TaskEstimate; operation?: SourceOperation }) {
  const { t } = useTranslation()
  const [cursors, setCursors] = useState<string[]>([])
  const [action, setAction] = useState<'' | 'convert' | 'skip'>('')
  const page = useSourcePlan(operation?.operation_id ?? null, operation?.plan_attempt ?? null, cursors.at(-1), action || undefined)
  const rows = operation ? page.data?.items ?? [] : estimate.series ?? []
  const skipped = operation ? estimate.n_skipped : rows.filter((r) => r.action === 'skip').length
  const total = operation ? page.data?.total ?? operation.plan_total : rows.length
  if (!operation && !rows.length) return null
  return (
    <details className="conv-plan" open={skipped > 0 && total <= 20}>
      <summary>{t('conv.plan', { count: total, skipped })}</summary>
      {operation ? <label className="conv-row"><span>{t('conv.planFilter')}</span><select className="input" value={action} onChange={(e) => { setAction(e.target.value as typeof action); setCursors([]) }}>
        <option value="">{t('conv.planAll')}</option><option value="convert">{t('conv.actionConvert')}</option><option value="skip">{t('conv.planSkipped')}</option>
      </select></label> : null}
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
      {page.isFetching ? <p role="status">{t('common.loading')}</p> : null}
      {page.error ? <ProblemCard error={page.error} /> : null}
      {operation ? <div className="conv-row"><span className="muted">{t('conv.planPage', { n: rows.length, total })}</span>
        <button type="button" className="btn btn-sm" disabled={!cursors.length || page.isFetching} onClick={() => setCursors((values) => values.slice(0, -1))}>{t('conv.previousPage')}</button>
        <button type="button" className="btn btn-sm" disabled={!page.data?.next_cursor || page.isFetching} onClick={() => page.data?.next_cursor && setCursors((values) => [...values, page.data!.next_cursor!])}>{t('conv.nextPage')}</button>
      </div> : null}
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
  const at = SCAN_STAGES.indexOf(current as (typeof SCAN_STAGES)[number])
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
      {at < 0 ? <p>{t(`conv.status.${current}`, { defaultValue: t(`conv.stage.${current}`, { done: progress?.done ?? 0, total: progress?.total ?? 0 }) })}</p> : null}
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
  const { pid, close, createFrom, patch, step, source, browse, target, settings, estimate, error, scan, run, minimized, operationId } = c
  const qc = useQueryClient()
  const operationQuery = useSourceOperation(operationId)
  const operation = operationQuery.data
  const operations = useSourceOperations().data ?? []
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
  const legacyWorkspace = useWorkspaceRun(!operationId && run?.kind === 'dataset' ? run.rid : null).data
  const legacyProject = useTaskRun(pid ?? '', !operationId && run?.kind === 'project' ? run.rid : null).data
  const linked = operation?.conversion_run
  const phase = operation?.phase_run
  const phasePending = !!phase && isTaskRunPending(phase.status)
  const ws = linked && 'dataset_dir' in linked ? linked : legacyWorkspace
  const prun = linked && 'runtime' in linked ? linked : legacyProject
  const resourceWait = ws?.resource_wait ?? prun?.resource_wait
  const intoProject = target === 'project' && !!pid
  const needsDerived = intoProject && !!project && !project.path_roots.some((r) => r.role === 'derived')
  const taskSettings = { target_profile: settings.target_profile, phase_analyzer: settings.phase_analyzer, anonymize: settings.anonymize }
  const setSettings = (s: Partial<Draft['settings']>) => patch({ requestKey: null, settings: { ...settings, ...s } })
  const scanProgress = useEstimateProgress(scan?.id ?? null).data
  const elapsed = useElapsed(operation ? Date.parse(operation.created_at) : scan?.started ?? null)
  const inventoryCounts = operation?.summary?.complete && (!isTaskRunPending(operation.status) || linked) ? operation.summary : operation?.progress
  const shownError = error ?? (operation?.problem ? toProblemError(Number(operation.problem.status ?? 500), operation.problem, operation.error ?? t('problemTitle.unknown')) : operation?.error && operation.status !== 'waiting_for_resources' ? new Error(operation.error) : null)
  useEffect(() => {
    if (!operation) return
    const current = useConverter.getState()
    const native = operation.conversion_run
    const snapshot = operation.settings ?? {}
    patch({
      source: operation.source, pid: operation.project_id,
      target: operation.project_id ? 'project' : 'dataset',
      settings: {
        ...current.settings,
        target_profile: typeof snapshot.target_profile === 'string' ? snapshot.target_profile : 'generic',
        anonymize: snapshot.anonymize === 'basic' ? 'basic' : 'none', phase_analyzer: snapshot.phase_analyzer !== false,
        name: native && 'dataset_dir' in native ? native.name : operation.dataset_name ?? current.settings.name,
      },
      estimate: operation.estimate ?? null,
      run: native ? { kind: operation.project_id ? 'project' : 'dataset', rid: native.run_id } : null,
      step: native ? current.step === 'result' && !isTaskRunPending(native.status) ? 'result' : 'run'
        : operation.work_kind === 'convert' ? 'run' : operation.stage === 'ready' ? 'estimate' : 'settings',
    })
  }, [operation, patch])

  // What is going on, for the run panel and the chip
  const runStatus = operation?.status ?? (run?.kind === 'dataset' ? ws?.status : prun?.status)
  const memoryMessage = runStatus !== 'waiting_for_resources' ? null
    : resourceWait?.reason === 'unknown_geometry' ? t('conv.memoryUnknown')
    : resourceWait?.reason === 'memory_budget' && typeof resourceWait.required_mb === 'number' && typeof resourceWait.budget_mb === 'number'
      ? t('conv.memoryBudget', { required: resourceWait.required_mb, budget: resourceWait.budget_mb }) : null
  const runFinished = !!runStatus && !isTaskRunPending(runStatus)
  let activity: Activity | null = null
  if ((busy && !operation && !run && !scan) || (operationId && !operation)) {
    activity = { label: t('conv.connecting'), done: 0, total: 0, finished: false }
  } else if (operation && !linked && operation.stage !== 'ready') {
    const progress = operation.progress ?? {}
    const stage = operation.progress_stage ?? (operation.stage === 'discovering' ? 'listing' : 'planning')
    const finished = !isTaskRunPending(operation.status)
    activity = { label: finished ? t(`conv.status.${operation.status}`, { defaultValue: operation.status }) : t(`conv.stage.${stage}`, { done: progress.done ?? progress.files ?? 0, total: progress.total ?? 0 }), done: progress.done ?? 0, total: progress.total ?? 0, finished, tone: finished && operation.status !== 'completed' ? 'error' : undefined }
  } else if (scan) {
    const s = scanProgress?.stage ?? 'check'
    activity = { label: `${t('conv.dryRunning')} · ${t(`conv.stage.${s}`, { done: scanProgress?.done ?? 0, total: scanProgress?.total ?? 0 })}`, done: scanProgress?.done ?? 0, total: s === 'reading' || s === 'planning' ? scanProgress?.total ?? 0 : 0, finished: false }
  } else if (run) {
    const p = (run.kind === 'dataset' ? ws?.progress : prun?.progress) as Record<string, number | string | null | undefined> | undefined
    const done = Number(p?.done ?? 0)
    const total = Number(p?.total ?? 0)
    if (runFinished) {
      const tone = runStatus === 'completed' ? 'ok' : runStatus === 'completed_with_errors' ? 'warn' : 'error'
      activity = { label: t(`conv.status.${runStatus}`, { defaultValue: runStatus }), done, total, finished: true, tone }
    } else if (runStatus === 'waiting_for_resources' || runStatus === 'cancelling' || runStatus === 'cleanup_pending' || runStatus === 'reconciling') {
      activity = { label: t(`conv.status.${runStatus}`), done, total, finished: false }
    } else if (total === 0 && p?.stage) {
      // still scanning headers: the run reports the same stages as the dry run
      const sd = Number(p.stage_done ?? 0)
      const st = Number(p.stage_total ?? 0)
      activity = { label: `${t('conv.status.running')} · ${t(`conv.stage.${String(p.stage)}`, { done: sd, total: st })}`, done: sd, total: p.stage === 'reading' ? st : 0, finished: false }
    } else {
      const overall = total ? t('conv.converting', { done, total }) : t('conv.status.running')
      const label = p?.stage && p.stage !== 'converting' && p.stage !== 'admitted'
        ? t('conv.progressStage', { progress: overall, stage: t(`conv.stage.${String(p.stage)}`, { done: Number(p.stage_done ?? 0), total: Number(p.stage_total ?? 0) }) }) : overall
      activity = { label, done, total, finished: false }
    }
  } else if (estimate && step === 'estimate') {
    activity = { label: t('conv.dryRunDone', { n: estimate.n_units }), done: 1, total: 1, finished: true, tone: 'ok' }
  }
  const chipActivity: Activity | null = phase && runFinished ? {
    label: t('conv.phaseStatus', { status: t(`conv.status.${phase.status}`, { defaultValue: phase.status }) }),
    done: Number(phase.progress?.done ?? phase.counts?.ok ?? 0), total: Number(phase.progress?.total ?? phase.counts?.items ?? 0),
    finished: !phasePending, tone: phase.status === 'completed' ? 'ok' : phasePending ? undefined : 'warn',
  } : activity
  const working = busy || phasePending || (operationId ? !operation || isTaskRunPending(operation.status) : !!scan || (!!run && !runFinished))
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
      if (operationId && e instanceof ProblemError && e.status === 409) {
        void qc.invalidateQueries({ queryKey: keys.sourceOperation(operationId), exact: true })
      }
    } finally {
      setBusy(false)
    }
  }
  const saveOperation = (value: SourceOperation) => {
    qc.setQueryData(keys.sourceOperation(value.operation_id), value)
    void qc.invalidateQueries({ queryKey: keys.sourceOperations(), exact: true })
  }
  const controlPhase = (action: 'resume' | 'cancel') => guard(async () => {
    if (!phase || !operation) return
    const body = { expected_attempt: phase.attempts }
    if (operation.project_id) {
      if (action === 'resume') await api.resumeTaskRun(operation.project_id, phase.run_id, body)
      else await api.cancelTaskRun(operation.project_id, phase.run_id, body)
    } else if (action === 'resume') await api.resumeWorkspaceRun(phase.run_id, body)
    else await api.cancelWorkspaceRun(phase.run_id, body)
    await qc.invalidateQueries({ queryKey: keys.sourceOperation(operation.operation_id), exact: true })
    void qc.invalidateQueries({ queryKey: keys.workspaceRuns() })
    if (operation.project_id) void qc.invalidateQueries({ queryKey: keys.taskRuns(operation.project_id) })
  })
  const dryRun = () => guard(async () => {
    if (!source) return
    if (operation?.stage === 'ready' && !operation.conversion_run_id && operation.source === source && operation.project_id === (intoProject ? pid : null)) {
      saveOperation(await api.estimateSourceOperation(operation.operation_id, { expected_revision: operation.revision, expected_attempt: operation.attempt, settings: taskSettings, name: settings.name.trim() }))
      patch({ estimate: null, step: 'settings' })
      return
    }
    const requestKey = useConverter.getState().requestKey ?? scanId()
    patch({ requestKey })
    const value = await api.startSourceOperation({ path: source, project_id: intoProject ? pid : null, purpose: 'convert', prepare_plan: true, settings: taskSettings, name: settings.name.trim() || null, idempotency_key: requestKey })
    saveOperation(value)
    patch({ operationId: value.operation_id, estimate: null, run: null, scan: null, step: 'settings' })
  })
  const control = (action: 'cancel' | 'resume' | 'retry_failed') => guard(async () => {
    if (!operation) return
    const body = operation.pending_control?.action === action ? operation.pending_control.request : { expected_revision: operation.revision, expected_attempt: operation.attempt, ...(operation.conversion_run ? { expected_run_attempt: operation.conversion_run.attempts } : {}) }
    const value = await (action === 'cancel' ? api.cancelSourceOperation(operation.operation_id, body) : action === 'retry_failed' ? api.retryFailedSourceOperation(operation.operation_id, body) : api.resumeSourceOperation(operation.operation_id, body))
    saveOperation(value)
    if (action !== 'cancel') patch({ step: value.work_kind === 'convert' ? 'run' : 'settings' })
  })
  const cancelScan = () => {
    if (operation) void control('cancel')
  }
  const start = () =>
    guard(async () => {
      if (!source) return
      if (operation) {
        const generation = operation.summary?.generation
        if (typeof generation !== 'string' || !operation.plan_attempt) throw new Error(t('conv.planChanged'))
        saveOperation(await api.convertSourceOperation(operation.operation_id, { expected_revision: operation.revision, expected_attempt: operation.attempt, inventory_generation: generation, plan_attempt: operation.plan_attempt, name: settings.name.trim() || null }))
        patch({ step: 'run' })
        return
      }
      const selection = { source }
      if (intoProject && pid) {
        const r = await api.startTaskRun(pid, { task_id: 'dicom.convert', settings: taskSettings, selection })
        patch({ run: { kind: 'project', rid: r.run_id }, step: 'run' })
      } else {
        const r = await api.startWorkspaceRun({ task_id: 'dicom.convert', settings: taskSettings, selection, name: settings.name.trim() || null })
        patch({ run: { kind: 'dataset', rid: r.run_id }, step: 'run' })
      }
    })
  const cancelRun = () => operation ? control('cancel') : guard(async () => {
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
  const resumable = operation && ['cancelled', 'interrupted', 'failed', 'completed_with_errors'].includes(operation.status)
  const recovery = operation?.conversion_run
  const recoveryCounts = recovery?.counts
  const recoveryOutput = recovery ? ('dataset_dir' in recovery ? recovery.dataset_dir : recovery.output_dir) : null
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
      {minimized ? <ConverterChip activity={chipActivity} onShow={c.restore} onClose={close} /> : null}
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
          <div className="conv-row">
            <label className="conv-row"><span className="muted">{t('conv.recentOperations')}</span>
              <select className="input" aria-label={t('conv.recentOperations')} value={operationId ?? ''} onChange={(e) => { if (e.target.value) c.attach(e.target.value) }}>
                <option value="" disabled>{t('conv.chooseOperation')}</option>
                {operationId && !operations.some((value) => value.operation_id === operationId) ? <option value={operationId}>{t('conv.currentOperation')}</option> : null}
                {operations.map((value) => <option key={value.operation_id} value={value.operation_id}>{t('conv.operationOption', { source: value.source.split('/').at(-1), status: t(`conv.status.${value.status}`, { defaultValue: value.status }) })}</option>)}
              </select>
            </label>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={c.newOperation}>{t('conv.newOperation')}</button>
          </div>
          <StepBar step={step} />
          {operation ? <div className="conv-inventory" role="status" aria-live="polite">
            <dl>{(['folders', 'files', 'dicom', 'series', 'errors'] as const).map((key) => <div key={key}><dt>{t(`conv.counts.${key}`)}</dt><dd className="num">{String(inventoryCounts?.[key] ?? operation.summary?.[key] ?? 0)}</dd></div>)}</dl>
            <p className="muted conv-help">{t('conv.etaUnknown')}</p>
            {!operation.summary?.complete && !operation.conversion_run ? <p className="muted conv-help">{t('conv.provisional')}</p> : null}
          </div> : null}
          {step === 'source' ? (
            <div className="conv-body">
              <p className="muted">{t('conv.sourceHelp')}</p>
              <details open><summary>{t('conv.browseFolders')}</summary><FolderBrowser path={browse} onPath={(p) => patch({ browse: p, source: p, requestKey: null })} selected={source} onSelectFile={(p) => patch({ source: p, requestKey: null })} fileFilter={() => true} /></details>
              <div className="conv-row">
                <span className="mono conv-path">{source ?? t('conv.noSource')}</span>
                <button type="button" className="btn btn-primary" disabled={!source} onClick={() => patch({ step: 'settings', settings: { ...settings, name: settings.name || defaultDatasetName() } })}>{t('conv.next')}</button>
              </div>
            </div>
          ) : null}
          {step === 'settings' ? (
            <div className="conv-body">
              <div className="conv-row"><span className="muted">{t('conv.source')}</span><span className="mono conv-path">{source}</span><button type="button" className="btn btn-sm" disabled={working} onClick={() => patch({ step: 'source', operationId: null, requestKey: null })}>{t('conv.change')}</button></div>
              <fieldset className="conv-fields" disabled={working}>
                {pid ? (
                  <div className="field">
                    <span className="field-label">{t('conv.output')}</span>
                    <div className="seg" role="group">
                      <button type="button" aria-pressed={target === 'project'} onClick={() => patch({ target: 'project', requestKey: null })}>{t('conv.intoProject', { name: project?.name ?? '' })}</button>
                      <button type="button" aria-pressed={target === 'dataset'} onClick={() => patch({ target: 'dataset', requestKey: null })}>{t('conv.asDataset')}</button>
                    </div>
                  </div>
                ) : null}
                {target === 'dataset' ? (
                  <label className="field">
                    <span className="field-label">{t('conv.name')}</span>
                    <input className="input" aria-label={t('conv.name')} value={settings.name} onChange={(e) => setSettings({ name: e.target.value })} />
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
              {working ? (
                <ScanPanel progress={operation ? { stage: ['cancelling', 'cleanup_pending'].includes(operation.status) ? operation.status : operation.progress_stage ?? 'listing', done: operation.progress?.done ?? operation.progress?.files ?? 0, total: operation.progress?.total ?? 0 } : scanProgress} elapsed={elapsed} onCancel={cancelScan} onMinimize={c.minimize} />
              ) : (
                <div className="conv-row conv-actions">
                  <button type="button" className="btn btn-primary" disabled={needsDerived || busy} onClick={() => void dryRun()}>{t('conv.dryRun')}</button>
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
              <SeriesPlanTable key={`${operationId ?? 'legacy'}.${operation?.plan_attempt ?? ''}`} estimate={estimate} operation={operation} />
              {estimate.sample_errors?.length ? <div className="error-card">{estimate.sample_errors.join('; ')}</div> : null}
              <div className="conv-row conv-actions">
                <button type="button" className="btn" onClick={() => patch({ step: 'settings' })}>{t('conv.back')}</button>
                <button type="button" className="btn btn-primary" disabled={busy || estimate.n_units === 0} onClick={() => void start()}>{t('conv.run', { n: estimate.n_units })}</button>
              </div>
            </div>
          ) : null}
          {step === 'run' && activity ? <RunPanel activity={activity} onResult={() => patch({ step: 'result' })} onCancel={() => void cancelRun()} /> : null}
          {step === 'run' && memoryMessage ? <p className="muted conv-help" role="status">{memoryMessage}</p> : null}
          {step === 'run' && runStatus !== 'waiting_for_resources' && (ws?.error || prun?.error) ? <div className="error-card">{ws?.error ?? prun?.error}</div> : null}
          {step === 'result' && run?.kind === 'dataset' && ws ? (
            <div className="conv-body" data-testid="conv-result">
              <p>{t(ws.status === 'completed' ? 'conv.datasetReady' : 'conv.datasetPartial', { name: ws.name })}</p>
              <p className="mono conv-path">{dataset}</p>
              <p className="muted conv-help">{t(ws.status === 'completed' ? 'conv.datasetHelp' : 'conv.partialHelp')}</p>
              <div className="conv-row conv-actions">
                <button type="button" className="btn" disabled={ws.status !== 'completed'} onClick={openDataset}>{t('conv.open')}</button>
                <button type="button" className="btn btn-primary" disabled={ws.status !== 'completed'} onClick={() => setCreating(true)}>{t('conv.createProject')}</button>
              </div>
              <div className="conv-row">
                <select className="input" aria-label={t('conv.addTo')} value={addTo} onChange={(e) => setAddTo(e.target.value)}>
                  <option value="">{t('conv.pickProject')}</option>
                  {projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}
                </select>
                <button type="button" className="btn" disabled={!addTo || ws.status !== 'completed'} onClick={addToProject}>{t('conv.addTo')}</button>
              </div>
              <NewProjectDialog open={creating} onOpenChange={(o) => { setCreating(o); if (!o) close() }} prefill={{ path: dataset }} />
            </div>
          ) : null}
          {step === 'result' && run?.kind === 'project' ? (
            <div className="conv-body">
              <p>{t(prun?.status === 'completed' && !prun.error ? 'conv.projectDone' : 'conv.projectPartial')}</p>
              <div className="conv-row conv-actions"><button type="button" className="btn btn-primary" onClick={close}>{t('conv.close')}</button></div>
            </div>
          ) : null}
          {phase ? <PhasePanel phase={phase} busy={busy} conversionComplete={recovery?.status === 'completed'} onControl={(action) => void controlPhase(action)} /> : null}
          {resumable ? <div className="conv-body">
            {recoveryCounts ? <p className="muted num">{t('conv.recoveryCounts', { complete: 'ok' in recoveryCounts ? recoveryCounts.ok : (recoveryCounts.converted ?? 0) + (recoveryCounts.already_converted ?? 0), failed: recoveryCounts.failed ?? 0, pending: recoveryCounts.pending ?? 0 })}</p> : null}
            {recoveryOutput ? <code>{recoveryOutput}</code> : null}
            <div className="conv-row conv-actions">
            <button type="button" className="btn btn-primary" disabled={busy || !operation.cleanup_verified || (operation.pending_control != null && operation.pending_control.action !== 'resume')} onClick={() => void control('resume')}>{t('conv.resumePending')}</button>
            {recovery && (recoveryCounts?.failed ?? 0) > 0 ? <button type="button" className="btn" disabled={busy || !operation.cleanup_verified || (operation.pending_control != null && operation.pending_control.action !== 'retry_failed')} onClick={() => void control('retry_failed')}>{t('conv.retryFailed')}</button> : null}
            <button type="button" className="btn" disabled={busy} onClick={() => patch({ operationId: null, requestKey: null, step: 'settings', run: null })}>{t('conv.newDryRun')}</button>
            </div>
          </div> : null}
          {operationQuery.error ? <ProblemCard error={operationQuery.error} /> : null}
          {shownError ? (
            <ProblemCard
              error={shownError}
              labels={{ import_as: t('conv.createProject') }}
              onAction={{
                // AUD-A2-07: no DICOM here → view it, or make a project from its NIfTI files
                open: () => {
                  close()
                  if (source) openPath(navigate, source)
                },
                import_as: () => source && useConverter.setState({ createFrom: source }),
                choose_another_path: () => patch({ error: null, step: 'source', operationId: null, requestKey: null }),
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
