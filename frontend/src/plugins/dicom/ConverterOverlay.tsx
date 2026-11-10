// Without a project the output is a new write-once dataset folder `{destination}/{name}/`;
// inside a project it can convert into it instead. While it works, × and Escape minimize it to a
// chip that shows the progress and the work goes on server-side.
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
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
  useBatchPlan,
  useBatchPlans,
  keys,
  type SourceOperation,
  type TaskEstimate,
} from '../../api'
import { DerivedRootDialog, FolderBrowser, NewProjectDialog, useImportWizard, type WizardPrefill } from '../../features/import'
import { ProblemError, toProblemError } from '../../api/problem'
import { Button, ConfirmInline, Dialog, fmtBytes, fmtDate, fmtDuration, IndeterminateProgress, NumberInput, openPath, ProblemCard, Progress, useAnnounce } from '../../lib'
import { Icon, codicon } from '../../theme'
import { datasetSlug, defaultDatasetName, defaultDestination, rememberDestination, STEPS, useConverter, type Draft, type Step } from './store'
import { BatchBoard, BatchPlanList } from './BatchBoard'
import { BatchPreview } from './BatchPreview'
import { ConversionTime, CONV_STATUS, countLabel, DiscoveryNotes, operationCount, preparingKey, runCount, type StageCount } from './OperationProgress'
import { showOperationOutput } from './output'
import { PhasePanel } from './PhasePanel'
import './converter.css'

/** The dry run's stages in order (`pipeline.Stage`); `check` = the source is searched for DICOM */
const SCAN_STAGES = ['check', 'listing', 'reading', 'planning'] as const
const SOURCE_SCAN = ['counting', 'scanning', 'verifying']

/** Names a dry run (`progress_id`); `crypto.randomUUID` needs a secure context, a LAN http URL isn't */
const scanId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

/** The batch preview belongs to these inputs; changing any of them makes it stale */
const batchKeyOf = (d: Pick<Draft, 'source' | 'batchSize' | 'settings'>) => JSON.stringify([d.source, d.batchSize, d.settings])

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

/** Every series of the dry run, what happens to it and why, with its size */
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
      {page.error ? <ProblemCard error={page.error} onRetry={() => void page.refetch()} /> : null}
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
  return since == null ? null : Math.max(0, Math.round((now - since) / 1000))
}

/** The scan or analysis stages with the current one's counter, so a long scan is visibly alive */
function ScanPanel({ count, elapsed, onCancel, onMinimize, onOutput, opening = false, discovering = false, children }: { count: StageCount; elapsed: number | null; onCancel: () => void; onMinimize: () => void; onOutput?: () => void; opening?: boolean; discovering?: boolean; children?: ReactNode }) {
  const { t } = useTranslation()
  const stages: readonly string[] = opening ? ['listing', 'opening'] : discovering ? ['listing'] : SCAN_STAGES
  // Scanning the source is the first stage of every flow; its own sub-steps are not listed.
  const at = stages.indexOf(SOURCE_SCAN.includes(count.stage) ? stages[0]! : count.stage)
  return (
    <div className="conv-scan" data-testid="conv-scan">
      <ol className="conv-stages">
        {stages.map((s, i) => (
          <li key={s} data-state={i < at ? 'done' : i === at ? 'current' : 'pending'}>
            <Icon spec={codicon(i < at ? 'pass' : i === at ? 'loading' : 'circle-large')} className={i === at ? 'codicon-modifier-spin' : undefined} />
            <span>{i === at ? countLabel(t, count) : t(`conv.stageName.${s}`)}</span>
          </li>
        ))}
      </ol>
      {at < 0 ? <p>{countLabel(t, count)}</p> : null}
      {/* a stage that counted to its end but is still the current one is finishing: no full bar yet */}
      {count.total > 0 && count.done < count.total ? <Progress value={count.done} total={count.total} label={countLabel(t, count)} /> : <IndeterminateProgress label={countLabel(t, count)} />}
      {children}
      <div className="conv-row">
        <span className="muted conv-help">{elapsed == null ? t(opening || discovering ? 'open.keepsRunning' : 'conv.keepsRunning') : t(opening || discovering ? 'open.elapsed' : 'conv.elapsed', { time: fmtDuration(elapsed) })}</span>
        <span style={{ flex: 1 }} />
        {onOutput ? <button type="button" className="btn btn-sm" onClick={onOutput}>{t('conv.showOutput')}</button> : null}
        <button type="button" className="btn btn-sm" onClick={onMinimize}>{t('conv.minimize')}</button>
        <ConfirmInline question={t(opening ? 'open.cancelOpeningConfirm' : 'conv.cancelScanConfirm')} confirm={t('common.yesCancel')} onConfirm={onCancel} trigger={(ask) => <button type="button" className="btn btn-sm" onClick={ask}>{t(opening ? 'open.cancelOpening' : 'conv.cancelScan')}</button>} />
      </div>
    </div>
  )
}

/** `resumable`: a stopped conversion continues from the resume controls below instead of a result page */
function RunPanel({ activity, resumable, onResult, onCancel, onOutput, children }: { activity: Activity; resumable: boolean; onResult: () => void; onCancel: () => void; onOutput?: () => void; children?: ReactNode }) {
  const { t } = useTranslation()
  const stopped = activity.finished && activity.tone === 'error' && resumable
  return (
    <div className="conv-body">
      {stopped ? null : activity.total > 0 ? <Progress value={activity.done} total={activity.total} label={activity.label} /> : activity.finished ? null : <IndeterminateProgress label={activity.label} />}
      <p className="muted num">{activity.label}</p>
      {stopped ? <p className="muted conv-help">{t('conv.stopped')}</p> : children}
      <div className="conv-row conv-actions">
        {!activity.finished ? <ConfirmInline question={t('conv.cancelRunConfirm')} confirm={t('common.yesCancel')} onConfirm={onCancel} trigger={(ask) => <button type="button" className="btn" onClick={ask}>{t('conv.cancelRun')}</button>} />
          : stopped ? null : <button type="button" className="btn btn-primary" onClick={onResult}>{t('conv.showResult')}</button>}
        {onOutput ? <button type="button" className="btn" onClick={onOutput}>{t('conv.showOutput')}</button> : null}
      </div>
    </div>
  )
}

/** The minimized window: a notification-like chip with the progress and Show */
function ConverterChip({ activity, onShow, onClose, onCancel, title }: { activity: Activity | null; onShow: () => void; onClose: () => void; onCancel?: () => void; title: string }) {
  const { t } = useTranslation()
  const running = !!activity && !activity.finished
  const icon = running ? 'sync' : activity?.tone === 'error' ? 'error' : activity?.tone === 'warn' ? 'warning' : activity ? 'pass' : 'file-binary'
  return (
    <div className="overlay conv-chip" data-testid="conv-chip">
      <span style={{ color: `var(--${activity?.tone ?? 'accent'})`, display: 'inline-flex' }}>
        <Icon spec={codicon(icon)} className={running ? 'codicon-modifier-spin' : undefined} />
      </span>
      <div className="conv-chip-text">
        <strong>{title}</strong>
        <span className="muted">{activity?.label ?? t('conv.idle')}</span>
        {running ? activity.total > 0 ? <Progress value={activity.done} total={activity.total} label={activity.label} /> : <IndeterminateProgress label={activity.label} /> : null}
      </div>
      <button type="button" className="btn btn-sm" onClick={onShow}>{t('conv.show')}</button>
      {running && onCancel ? <ConfirmInline question={t('confirm.cancelJob')} confirm={t('common.yesCancel')} onConfirm={onCancel} trigger={(ask) => <button type="button" className="btn btn-sm" onClick={ask}>{t('common.cancel')}</button>} /> : null}
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
  const { pid, close, createFrom, patch, step, source, browse, target, settings, allowMixedVersions, error, scan, run, minimized, operationId, batchPlanId, batchMode, batchSize, batchPreview } = c
  const qc = useQueryClient()
  const operationQuery = useSourceOperation(operationId)
  const operation = operationQuery.data
  const estimate = operation?.estimate ?? null
  const plan = useBatchPlan(batchPlanId).data
  const previewPlan = useBatchPlan(batchPreview?.planId ?? null).data
  const isOpening = operation?.purpose === 'open'
  const isDiscovering = operation?.purpose === 'discover'
  const importStage = operation?.import_context?.step
  const isSourceOnly = isOpening || isDiscovering
  const title = t(isOpening ? 'open.backgroundTitle' : isDiscovering ? importStage === 'index' ? 'import.indexing' : importStage === 'previewing' ? 'import.preparingPreview' : 'import.backgroundTitle' : 'conv.title')
  const operations = useSourceOperations().data ?? []
  const project = useProject(pid ?? '').data
  const manifest = useTasks().data?.tasks.find((x) => x.manifest.id === 'dicom.convert')?.manifest
  const profiles = (manifest?.settings_schema?.properties as Record<string, { enum?: string[] }> | undefined)?.target_profile?.enum ?? ['generic']
  const [creating, setCreating] = useState(false)
  const [importDraft, setImportDraft] = useState<WizardPrefill | null>(null)
  const [derivedPrompt, setDerivedPrompt] = useState(false)
  const [addTo, setAddTo] = useState('')
  const [busy, setBusy] = useState(false)
  const projects = useProjects().data ?? []
  const datasets = useWorkspaceRuns().data ?? []
  const slug = datasetSlug(settings.name.trim() || defaultDatasetName())
  const destination = settings.destination.trim().replace(/(.)\/+$/, '$1')
  const taken = new Set(datasets.map((r) => r.dataset_dir))
  const inDestination = (name: string) => `${destination.replace(/\/$/, '')}/${name}`
  const clash = target === 'dataset' && taken.has(inDestination(slug)) ? { name: slug } : null
  let nextFree = slug
  for (let n = 1; taken.has(inDestination(nextFree)); n++) nextFree = `${slug}-${n}`
  const legacyWorkspace = useWorkspaceRun(!operationId && run?.kind === 'dataset' ? run.rid : null).data
  const legacyProject = useTaskRun(pid ?? '', !operationId && run?.kind === 'project' ? run.rid : null).data
  const linked = operation?.conversion_run
  const phase = operation?.phase_run
  const phasePending = !!phase && isTaskRunPending(phase.status)
  const ws = linked && 'dataset_dir' in linked ? linked : legacyWorkspace
  const prun = linked && 'runtime' in linked ? linked : legacyProject
  const resourceWait = ws?.resource_wait ?? prun?.resource_wait
  const conversionTime = run || linked ? ws?.conversion_time ?? prun?.conversion_time : step === 'estimate' ? estimate?.conversion_time : null
  const intoProject = target === 'project' && !!pid
  const needsDerived = intoProject && !!project && !project.path_roots.some((r) => r.role === 'derived')
  const taskSettings = { target_profile: settings.target_profile, phase_analyzer: settings.phase_analyzer, anonymize: settings.anonymize }
  const datasetDestination = intoProject ? {} : { destination: destination || null }
  const setSettings = (s: Partial<Draft['settings']>) => patch({ requestKey: null, settings: { ...settings, ...s } })
  const scanProgress = useEstimateProgress(scan?.id ?? null).data
  // An operation can run many attempts over days and carries no attempt start, so only a scan started here is timed.
  // server operations count from their creation; a local scan from its start
  const elapsed = useElapsed(operation ? (isTaskRunPending(operation.status) ? Date.parse(operation.created_at) : null) : scan?.started ?? null)
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
        destination: operation.dataset_destination ?? (current.settings.destination || defaultDestination(operation.source)),
      },
      run: native ? { kind: operation.project_id ? 'project' : 'dataset', rid: native.run_id } : null,
      step: native ? current.step === 'result' && !isTaskRunPending(native.status) ? 'result' : 'run'
        : operation.work_kind === 'convert' ? 'run' : operation.stage === 'ready' ? 'estimate' : 'settings',
    })
  }, [operation, patch])

  const prepared = useMutation({
    mutationFn: (id: string) => api.openSourceOperation(id),
    onSuccess: (session) => {
      qc.setQueryData(keys.open(session.sid), session)
      close()
      navigate(`/open/${encodeURIComponent(session.sid)}`, { replace: true })
    },
    onError: (error) => patch({ error }),
  })
  const discovery = useMutation({
    mutationFn: async (record: SourceOperation) => ({ record, result: await api.sourceOperationDetection(record.operation_id) }),
    onSuccess: ({ record, result }) => {
      if (useConverter.getState().operationId !== record.operation_id) return
      const context = record.import_context
      const draft: WizardPrefill = {
        path: result.path, kind: result.kind, discoveryId: record.operation_id,
        alias: context?.alias ?? 'DATA', adapter: context?.adapter ?? undefined,
        add: context?.add ?? false, options: context?.options ?? {},
        step: context?.step === 'index' ? 'index' : context?.step === 'preview' ? 'preview' : 'detect',
        reconstruct: context?.reconstruct ?? false, anonymize: context?.anonymize ?? false,
        revision: record.revision, attempt: record.attempt,
      }
      qc.setQueryData(keys.sourceDetection(record.operation_id), result)
      if (record.project_id) {
        c.hideForImport(record.operation_id)
        navigate(`/p/${record.project_id}`)
        useImportWizard.getState().open(record.project_id, draft)
      } else {
        c.minimize()
        setImportDraft(draft)
      }
    },
    onError: (error) => patch({ error }),
  })
  const { mutate: openPrepared } = prepared
  const showOpen = useCallback(() => {
    if (!operationId) return
    patch({ autoOpen: false, error: null })
    openPrepared(operationId)
  }, [operationId, patch, openPrepared])
  useEffect(() => {
    if (c.autoOpen && !minimized && operation?.stage === 'opened' && operation.status === 'completed') void showOpen()
  }, [c.autoOpen, minimized, operation, showOpen])

  const runStatus = operation?.status ?? (run?.kind === 'dataset' ? ws?.status : prun?.status)
  const memoryMessage = runStatus !== 'waiting_for_resources' ? null
    : resourceWait?.reason === 'unknown_geometry' ? t('conv.memoryUnknown')
    : resourceWait?.reason === 'memory_budget' && typeof resourceWait.required_mb === 'number' && typeof resourceWait.budget_mb === 'number'
      ? t('conv.memoryBudget', { required: resourceWait.required_mb, budget: resourceWait.budget_mb }) : null
  const runFinished = !!runStatus && !isTaskRunPending(runStatus)
  const lost = !operation && !!operationQuery.error
  // The docked Output panel would sit behind this window, so the window steps aside first.
  const showLog = operation ? () => { c.minimize(); showOperationOutput(operation) } : undefined
  const plans = useBatchPlans().data ?? []
  const owner = plans.flatMap((plan) => plan.batches.map((batch) => ({ plan, batch }))).find((x) => !!operationId && x.batch.operation_id === operationId) ?? null
  const analysing = step === 'settings' && operation?.purpose === 'convert' && !linked && isTaskRunPending(operation.status)
  // The counter that means something right now, so a bar never reads "0 / 0" or "N / 0"
  const scanCount: StageCount | null = operation
    ? ['cancelling', 'cleanup_pending'].includes(operation.status) ? { stage: operation.status, done: 0, total: 0 } : operationCount(operation)
    : scan ? { stage: scanProgress?.stage ?? 'check', done: scanProgress?.done ?? 0, total: scanProgress?.stage === 'reading' || scanProgress?.stage === 'planning' ? scanProgress.total ?? 0 : 0 } : null
  const runProgress = (run?.kind === 'dataset' ? ws?.progress : prun?.progress) as Record<string, number | string | null | undefined> | undefined
  let activity: Activity | null = null
  if ((busy && !operation && !run && !scan) || (operationId && !operation && !lost)) {
    activity = { label: t('conv.connecting'), done: 0, total: 0, finished: false }
  } else if (operation && scanCount && !linked && operation.stage !== 'ready') {
    const finished = !isTaskRunPending(operation.status)
    activity = { label: finished ? t(CONV_STATUS[operation.status]) : countLabel(t, scanCount), done: scanCount.done, total: scanCount.total, finished, tone: finished && operation.status !== 'completed' ? 'error' : undefined }
  } else if (scan && scanCount) {
    activity = { label: countLabel(t, scanCount), done: scanCount.done, total: scanCount.total, finished: false }
  } else if (run) {
    const count = runCount(runProgress)
    if (runFinished) {
      const tone = runStatus === 'completed' ? 'ok' : runStatus === 'completed_with_errors' ? 'warn' : 'error'
      const p = runProgress
      activity = { label: t(CONV_STATUS[runStatus]), done: Number(p?.done ?? 0), total: Number(p?.total ?? 0), finished: true, tone }
    } else if (runStatus === 'waiting_for_resources' || runStatus === 'cancelling' || runStatus === 'cleanup_pending' || runStatus === 'reconciling') {
      activity = { label: t(CONV_STATUS[runStatus]), done: count.done, total: count.total, finished: false }
    } else {
      activity = { label: countLabel(t, count), done: count.done, total: count.total, finished: false }
    }
  } else if (estimate && step === 'estimate') {
    activity = { label: t('conv.dryRunDone', { n: estimate.n_units }), done: 1, total: 1, finished: true, tone: 'ok' }
  }
  const planDone = plan?.batches.filter((b) => b.status === 'completed').length ?? 0
  const planActivity: Activity | null = plan ? {
    label: t('conv.batches.chip', { done: planDone, total: plan.batches.length }), done: planDone, total: plan.batches.length,
    finished: plan.status !== 'running', tone: plan.status === 'completed' ? 'ok' : plan.status === 'paused' ? 'warn' : undefined,
  } : null
  const chipActivity: Activity | null = planActivity ?? (phase && runFinished ? {
    label: t('conv.phaseStatus', { status: t(CONV_STATUS[phase.status]) }),
    done: Number(phase.progress?.done ?? phase.counts?.ok ?? 0), total: Number(phase.progress?.total ?? phase.counts?.items ?? 0),
    finished: !phasePending, tone: phase.status === 'completed' ? 'ok' : phasePending ? undefined : 'warn',
  } : activity)
  // Screen readers hear milestones only: what runs now and how it ended, never the counters
  const milestone = chipActivity === activity && activity && !activity.finished
    ? `${title}: ${scanCount && !run ? countLabel(t, { ...scanCount, done: 0, total: 0 }) : run && runStatus ? t(CONV_STATUS[runStatus]) : activity.label}`
    : chipActivity ? `${title}: ${chipActivity.label}` : null
  useAnnounce(milestone)
  const working = busy || prepared.isPending || phasePending || plan?.status === 'running' || (operationId ? (!operation && !lost) || (!!operation && isTaskRunPending(operation.status)) : !!scan || (!!run && !runFinished))
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
      saveOperation(await api.estimateSourceOperation(operation.operation_id, { expected_revision: operation.revision, expected_attempt: operation.attempt, settings: taskSettings, name: settings.name.trim(), ...datasetDestination }))
      patch({ step: 'settings' })
      return
    }
    const requestKey = useConverter.getState().requestKey ?? scanId()
    patch({ requestKey })
    const value = await api.startSourceOperation({ path: source, project_id: intoProject ? pid : null, purpose: 'convert', prepare_plan: true, settings: taskSettings, name: settings.name.trim() || null, ...datasetDestination, idempotency_key: requestKey })
    saveOperation(value)
    patch({ operationId: value.operation_id, run: null, scan: null, step: 'settings' })
  })
  const control = (action: 'cancel' | 'resume' | 'retry_failed') => guard(async () => {
    if (!operation) return
    const body = operation.pending_control?.action === action ? operation.pending_control.request : { expected_revision: operation.revision, expected_attempt: operation.attempt, ...(operation.conversion_run ? { expected_run_attempt: operation.conversion_run.attempts } : {}) }
    const cancelCurrent = async () => {
      const current = operation.pending_control ? operation : await api.getSourceOperation(operation.operation_id)
      saveOperation(current)
      if (current.attempt !== operation.attempt || current.conversion_run?.run_id !== operation.conversion_run?.run_id || current.conversion_run?.attempts !== operation.conversion_run?.attempts) throw new Error(t('conv.attemptChanged'))
      const fence = current.pending_control?.action === 'cancel' ? current.pending_control.request : { expected_revision: current.revision, expected_attempt: current.attempt, ...(current.conversion_run ? { expected_run_attempt: current.conversion_run.attempts } : {}) }
      return api.cancelSourceOperation(current.operation_id, fence)
    }
    let value: SourceOperation
    if (action === 'cancel') {
      try {
        value = await cancelCurrent()
      } catch (error) {
        if (!(error instanceof ProblemError) || error.status !== 409 || operation.pending_control) throw error
        value = await cancelCurrent()
      }
    } else value = await (action === 'retry_failed' ? api.retryFailedSourceOperation(operation.operation_id, body) : api.resumeSourceOperation(operation.operation_id, body))
    saveOperation(value)
    if (action !== 'cancel') patch({ step: value.work_kind === 'convert' ? 'run' : 'settings' })
  })
  const cancelScan = () => {
    if (operation) void control('cancel')
  }
  /** The plan the batch settings would run, created on the server so its folders and files can be counted */
  const createPreview = () => guard(async () => {
    const s = useConverter.getState()
    if (!s.source) return
    const previous = s.batchPreview
    const created = await api.createSourceBatchPlan({
      path: s.source, batch_size: s.batchSize, auto: false, name: s.settings.name.trim() || defaultDatasetName(), destination: s.settings.destination.trim() || null,
      settings: { target_profile: s.settings.target_profile, phase_analyzer: s.settings.phase_analyzer, anonymize: s.settings.anonymize },
    })
    qc.setQueryData(keys.batchPlan(created.plan_id), created)
    patch({ batchPreview: { planId: created.plan_id, key: batchKeyOf(s) } })
    if (previous) void api.controlSourceBatchPlan(previous.planId, 'cancel').catch(() => undefined)
  })
  const toggleBatches = (on: boolean) => {
    patch({ batchMode: on, error: null })
    if (on) void createPreview()
    else if (batchPreview) {
      void api.controlSourceBatchPlan(batchPreview.planId, 'cancel').catch(() => undefined)
      patch({ batchPreview: null })
    }
  }
  const openBoard = () => {
    if (!batchPreview) return
    useConverter.setState({ batchPlanId: batchPreview.planId, batchMode: false, batchPreview: null })
  }
  /** After the size warning or the limit error: stop this scan and plan the source in batches instead */
  const suggestBatches = () => guard(async () => {
    if (operation && isTaskRunPending(operation.status)) await control('cancel')
    patch({ operationId: null, requestKey: null, run: null, scan: null, step: 'settings', target: 'dataset', pid: null, batchMode: true })
    await createPreview()
  })
  const start = () =>
    guard(async () => {
      if (!source) return
      if (!intoProject && destination) rememberDestination(destination)
      if (operation) {
        const generation = operation.summary?.generation
        if (typeof generation !== 'string' || !operation.plan_attempt) throw new Error(t('conv.planChanged'))
        saveOperation(await api.convertSourceOperation(operation.operation_id, { expected_revision: operation.revision, expected_attempt: operation.attempt, inventory_generation: generation, plan_attempt: operation.plan_attempt, name: settings.name.trim() || null, ...(operation.project_id ? {} : { destination: destination || null }), ...(operation.project_id && allowMixedVersions ? { allow_mixed_versions: true } : {}) }))
        patch({ step: 'run' })
        return
      }
      const selection = { source }
      if (intoProject && pid) {
        const r = await api.startTaskRun(pid, { task_id: 'dicom.convert', settings: taskSettings, selection, ...(allowMixedVersions ? { allow_mixed_versions: true } : {}) })
        patch({ run: { kind: 'project', rid: r.run_id }, step: 'run' })
      } else {
        const r = await api.startWorkspaceRun({ task_id: 'dicom.convert', settings: taskSettings, selection, name: settings.name.trim() || null, ...datasetDestination })
        patch({ run: { kind: 'dataset', rid: r.run_id }, step: 'run' })
      }
    })
  // DCM-34: the committed series of a project conversion with failures, only on request
  const registerConverted = (projectId: string, runId: string) => guard(async () => {
    await api.registerConvertedRun(projectId, runId)
    void qc.invalidateQueries({ queryKey: keys.taskRuns(projectId) })
  })
  const cancelRun = () => operation ? control('cancel') : guard(async () => {
      if (!run) return
      if (run.kind === 'project' && pid) await api.cancelTaskRun(pid, run.rid)
      else await api.cancelWorkspaceRun(run.rid)
    })
  const onOpenChange = (o: boolean) => {
    if (o) return
    if (working) c.minimize()
    else {
      if (batchPreview) void api.controlSourceBatchPlan(batchPreview.planId, 'cancel').catch(() => undefined)
      close()
    }
  }
  const dataset = ws?.dataset_dir ?? ''
  const projection = operation?.summary?.inventory_projection as { warning?: boolean } | null | undefined
  const suggestsBatches = !!operation && operation.purpose === 'convert' && !operation.conversion_run && !operation.project_id && (!!projection?.warning || operation.summary?.limit_reason === 'inventory_bytes')
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
      {minimized ? <ConverterChip title={title} activity={chipActivity} onShow={c.restore} onClose={close} onCancel={working && operation && ['queued', 'running', 'waiting_for_resources'].includes(operation.status) ? () => void cancelScan() : undefined} /> : null}
      <Dialog
        open={!minimized}
        onOpenChange={onOpenChange}
        title={title}
        icon={codicon('file-binary')}
        size="lg"
        dismissible={false}
        actions={
          <button type="button" className="icon-btn" aria-label={t('conv.minimizeWindow')} title={t('conv.minimizeHint')} onClick={c.minimize}>
            <Icon spec={codicon('chrome-minimize')} />
          </button>
        }
      >
        <div className="conv">
          <div className="conv-row">
            <label className="conv-row"><span className="muted">{t('conv.recentOperations')}</span>
              <select className="input" aria-label={t('conv.recentOperations')} value={batchPlanId ? '' : operationId ?? ''} onChange={(e) => { if (e.target.value) c.attach(e.target.value) }}>
                <option value="" disabled>{t('conv.chooseOperation')}</option>
                {operationId && !operations.some((value) => value.operation_id === operationId) ? <option value={operationId}>{t('conv.currentOperation')}</option> : null}
                {operations.map((value) => {
                  const preparing = preparingKey(value)
                  const status = preparing ? t(`conv.batches.status.${preparing}`) : t(CONV_STATUS[value.status])
                  const name = value.dataset_name ?? value.source.split('/').at(-1)
                  return <option key={value.operation_id} value={value.operation_id}>{t('conv.operationOption', { name, status, date: fmtDate(value.created_at) })}</option>
                })}
              </select>
            </label>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={c.newOperation}>{t('conv.newOperation')}</button>
          </div>
          {batchPlanId ? <BatchBoard planId={batchPlanId} onNew={c.newOperation} onProjectClosed={close} onOpenOperation={(id) => c.attach(id)} /> : <>
          {owner ? <div className="conv-row conv-crumb">
            <button type="button" className="btn btn-sm" onClick={() => useConverter.setState({ batchPlanId: owner.plan.plan_id })}>
              <Icon spec={codicon('arrow-left')} /> {t('conv.backToBatches')}
            </button>
            <span className="muted">{t('conv.inPlan', { batch: owner.batch.name, plan: owner.plan.name })}</span>
          </div> : null}
          {!isSourceOnly ? <StepBar step={analysing ? 'estimate' : step} /> : null}
          {/* DICOM counts mean nothing while a file or folder opens */}
          {operation && !isOpening && (step === 'settings' || step === 'estimate') ? <div className="conv-inventory">
            <dl>{(['folders', 'files', 'dicom', 'rejected', 'series', 'errors'] as const).map((key) => <div key={key}><dt>{t(`conv.counts.${key}`)}</dt><dd className="num">{String(inventoryCounts?.[key] ?? operation.summary?.[key] ?? 0)}</dd></div>)}</dl>
            {operation.summary?.rejections && typeof operation.summary.rejections === 'object' ? <ul aria-label={t('conv.rejectedCandidates')}>{Object.entries(operation.summary.rejections).map(([code, count]) => <li key={code}>{t('conv.rejectedReason', { reason: t(`conv.rejection.${code}`, { defaultValue: code }), count: Number(count) })}</li>)}</ul> : null}
            {!operation.summary?.complete && !operation.conversion_run && !(operation.progress?.files_total || operation.progress_stage === 'counting') ? <p className="muted conv-help">{t('conv.provisional')}</p> : null}
            {suggestsBatches ? <div className="conv-row"><button type="button" className="btn btn-sm" disabled={busy} onClick={() => void suggestBatches()}>{t('conv.batches.suggest')}</button></div> : null}
          </div> : null}
          {isSourceOnly ? <div className="conv-body">
            {/* opening names the file or folder, not its server path (the path is the tooltip) */}
            <code className="conv-path" title={source ?? undefined}>{isOpening ? source?.split('/').filter(Boolean).at(-1) : source}</code>
            {working && scanCount ? <ScanPanel opening={isOpening} discovering={isDiscovering} count={operation.stage === 'import_index' ? { stage: 'import_index', done: operation.progress?.done ?? 0, total: operation.progress?.total ?? 0 } : scanCount} elapsed={elapsed} onCancel={cancelScan} onMinimize={c.minimize} /> : operation.stage === 'opened' && operation.status === 'completed' ? <>
              <p>{t('open.prepared')}</p>
              <button type="button" className="btn btn-primary" disabled={busy || prepared.isPending} onClick={showOpen}>{t('open.openPrepared')}</button>
            </> : isDiscovering && operation.status === 'completed' ? <>
              <p>{t(importStage === 'index' ? 'import.indexReady' : importStage === 'preview' ? 'import.previewReady' : 'import.discovered')}</p>
              <button type="button" className="btn btn-primary" disabled={busy || discovery.isPending} onClick={() => discovery.mutate(operation)}>{t('import.continueImport')}</button>
            </> : null}
            {isDiscovering && operation.error ? <p className="error-card" role="alert">{operation.error}</p> : null}
            {isDiscovering && importStage === 'previewing' && operation.cleanup_verified && !working ? <button type="button" className="btn" disabled={discovery.isPending} onClick={() => discovery.mutate(operation)}>{t('import.editOptions')}</button> : null}
          </div> : null}
          {!isSourceOnly && step === 'source' ? (
            <div className="conv-body">
              <p className="muted">{t('conv.sourceHelp')}</p>
              <details open><summary>{t('conv.browseFolders')}</summary><FolderBrowser path={browse} onPath={(p) => patch({ browse: p, source: p, requestKey: null })} selected={source} onSelectFile={(p) => patch({ source: p, requestKey: null })} fileFilter={() => true} /></details>
              <div className="conv-row">
                <span className="mono conv-path">{source ?? t('conv.noSource')}</span>
                <Button className="btn btn-primary" disabled={!source} reason={t('reason.chooseSource')} onClick={() => patch({ step: 'settings', settings: { ...settings, name: settings.name || defaultDatasetName(), destination: settings.destination || defaultDestination(source) } })}>{t('conv.next')}</Button>
              </div>
            </div>
          ) : null}
          {!isSourceOnly && step === 'settings' ? (
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
                    {clash ? <span className="conv-help" role="note" style={{ color: 'var(--warn)' }}>{t('conv.nameTaken', { name: clash.name, next: nextFree })}</span> : null}
                    <span className="muted conv-help">{t('conv.nameHelp')}</span>
                  </label>
                ) : null}
                {target === 'dataset' ? (
                  <div className="field">
                    <span className="field-label">{t('conv.destination')}</span>
                    <div className="conv-row"><span className="mono conv-path" title={t('conv.destinationResult')}>{destination ? inDestination(clash ? nextFree : slug) : t('conv.noDestination')}</span></div>
                    <details><summary>{t('conv.chooseDestination')}</summary><FolderBrowser path={destination || browse} onPath={(p) => setSettings({ destination: p ?? '' })} selected={destination} /></details>
                    <span className="muted conv-help">{t('conv.destinationHelp')}</span>
                  </div>
                ) : null}
                <label className="field">
                  <span className="field-label">{t('conv.profile')}</span>
                  <select className="input" value={settings.target_profile} onChange={(e) => setSettings({ target_profile: e.target.value })}>
                    {profiles.map((p) => <option key={p} value={p}>{t(`conv.profiles.${p}`, { defaultValue: p })}</option>)}
                  </select>
                  <span className="muted conv-help">{t('conv.profileHelp')}</span>
                </label>
                {target === 'dataset' && !operationId ? <>
                  <label className="conv-check">
                    <input type="checkbox" checked={batchMode} onChange={(e) => toggleBatches(e.target.checked)} />
                    {t('conv.batches.toggle')}
                  </label>
                  {batchMode ? <label className="field">
                    <span className="field-label">{t('conv.batches.size')}</span>
                    <NumberInput className="input" aria-label={t('conv.batches.size')} value={batchSize} min={1} onChange={(n) => { if (n && n >= 1) patch({ batchSize: Math.floor(n) }) }} />
                  </label> : null}
                </> : null}
                <label className="conv-check">
                  <input type="checkbox" checked={settings.phase_analyzer} onChange={(e) => setSettings({ phase_analyzer: e.target.checked })} />
                  {t('conv.phase')}
                </label>
                <label className="conv-check">
                  <input type="checkbox" checked={settings.anonymize === 'basic'} onChange={(e) => setSettings({ anonymize: e.target.checked ? 'basic' : 'none' })} />
                  {t('conv.anonymize')}
                </label>
                {intoProject ? <label className="conv-check" title={t('conv.mixedVersionsHelp')}>
                  <input type="checkbox" checked={allowMixedVersions} onChange={(e) => patch({ allowMixedVersions: e.target.checked })} />
                  {t('conv.mixedVersions')}
                </label> : null}
              </fieldset>
              <p className="muted conv-help">{t('conv.phiNotice')}</p>
              {needsDerived ? (
                <div className="error-card">
                  {t('conv.needsDerived')} <button type="button" className="btn btn-sm" onClick={() => setDerivedPrompt(true)}>{t('conv.chooseDerived')}</button>
                </div>
              ) : null}
              {working ? (
                scanCount ? <ScanPanel count={scanCount} elapsed={elapsed} onCancel={cancelScan} onMinimize={c.minimize} onOutput={showLog}>{operation ? <DiscoveryNotes operation={operation} /> : null}</ScanPanel>
                  : <p role="status">{t('conv.connecting')}</p>
              ) : batchMode && target === 'dataset' ? <>
                {previewPlan ? <BatchPreview plan={previewPlan} /> : <p role="status">{t('common.loading')}</p>}
                <div className="conv-row conv-actions">
                  {batchPreview && batchPreview.key !== batchKeyOf({ source, batchSize, settings }) ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void createPreview()}>{t('conv.batches.update')}</button>
                    : <button type="button" className="btn btn-primary" disabled={busy || !previewPlan} onClick={openBoard}>{t('conv.batches.review')}</button>}
                </div>
              </> : (
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
              <ConversionTime value={conversionTime} />
              <SeriesPlanTable key={`${operationId ?? 'legacy'}.${operation?.plan_attempt ?? ''}`} estimate={estimate} operation={operation} />
              {estimate.sample_errors?.length ? <div className="error-card">{estimate.sample_errors.join('; ')}</div> : null}
              <div className="conv-row conv-actions">
                <button type="button" className="btn" onClick={() => patch({ step: 'settings' })}>{t('conv.back')}</button>
                <button type="button" className="btn btn-primary" disabled={busy || estimate.n_units === 0} onClick={() => void start()}>{t('conv.run', { n: estimate.n_units })}</button>
              </div>
            </div>
          ) : null}
          {step === 'run' && activity ? <RunPanel activity={activity} resumable={!!resumable} onOutput={showLog} onResult={() => patch({ step: 'result' })} onCancel={() => void cancelRun()}>
            {runProgress?.stage === 'converting' || Number(runProgress?.bytes_total ?? 0) > 0 || conversionTime?.basis === 'history' ? <ConversionTime value={conversionTime} progress={runProgress} /> : null}
          </RunPanel> : null}
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
              <NewProjectDialog open={creating} onOpenChange={setCreating} onCreated={close} prefill={{ path: dataset }} />
            </div>
          ) : null}
          {step === 'result' && run?.kind === 'project' ? (
            <div className="conv-body">
              <p>{t(runStatus === 'completed' && !prun?.error ? 'conv.projectDone' : 'conv.projectPartial')}</p>
              <div className="conv-row conv-actions"><button type="button" className="btn btn-primary" onClick={close}>{t('conv.close')}</button></div>
            </div>
          ) : null}
          {phase ? <PhasePanel phase={phase} busy={busy} conversionComplete={recovery?.status === 'completed'} onControl={(action) => void controlPhase(action)} /> : null}
          {resumable ? <div className="conv-body">
            {recoveryCounts ? <p className="muted num">{t('conv.recoveryCounts', { complete: 'ok' in recoveryCounts ? recoveryCounts.ok : (recoveryCounts.converted ?? 0) + (recoveryCounts.already_converted ?? 0), failed: recoveryCounts.failed ?? 0, pending: recoveryCounts.pending ?? 0 })}</p> : null}
            {recoveryOutput ? <code>{recoveryOutput}</code> : null}
            <div className="conv-row conv-actions">
            {operation.status !== 'completed_with_errors' || (recoveryCounts?.pending ?? 0) > 0 ? <Button className="btn btn-primary" reason={t(operation.cleanup_verified ? 'reason.working' : 'reason.cleanup')} disabled={busy || !operation.cleanup_verified || (operation.pending_control != null && operation.pending_control.action !== 'resume')} onClick={() => void control('resume')}>{t('conv.resumePending')}</Button> : null}
            {recovery && (recoveryCounts?.failed ?? 0) > 0 ? <Button className="btn" reason={t(operation.cleanup_verified ? 'reason.working' : 'reason.cleanup')} disabled={busy || !operation.cleanup_verified || (operation.pending_control != null && operation.pending_control.action !== 'retry_failed')} onClick={() => void control('retry_failed')}>{t('conv.retryFailed')}</Button> : null}
            {operation.project_id && operation.conversion_run_id && operation.status === 'completed_with_errors' && (recoveryCounts?.pending ?? 0) === 0 ? <Button className="btn" title={t('conv.registerConvertedHelp')} reason={t(operation.cleanup_verified ? 'reason.working' : 'reason.cleanup')} disabled={busy || !operation.cleanup_verified} onClick={() => void registerConverted(operation.project_id as string, operation.conversion_run_id as string)}>{t('conv.registerConverted')}</Button> : null}
            </div>
          </div> : null}
          {operationQuery.error ? <ProblemCard error={operationQuery.error} onRetry={() => void operationQuery.refetch()} /> : null}
          </>}
          <BatchPlanList current={batchPlanId} onOpen={(planId) => useConverter.setState({ batchPlanId: planId })} />
          {shownError ? (
            <ProblemCard
              error={shownError}
              labels={{ import_as: t('conv.createProject') }}
              onAction={{
                // no DICOM here: view it, or make a project from its NIfTI files
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
      {importDraft ? <NewProjectDialog open onOpenChange={(o) => { if (!o) { setImportDraft(null); c.restore() } }} onCreated={close} prefill={importDraft} /> : null}
      {createFrom ? <NewProjectDialog open onOpenChange={(o) => { if (!o) useConverter.setState({ createFrom: null }) }} onCreated={close} prefill={{ path: createFrom, adapter: 'nifti-files' }} /> : null}
      {derivedPrompt && pid ? <DerivedRootDialog pid={pid} onClose={() => setDerivedPrompt(false)} /> : null}
    </>
  )
}
