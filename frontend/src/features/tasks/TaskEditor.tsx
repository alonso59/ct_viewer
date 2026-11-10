import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, useArchivedTaskRuns, useCase, useJobs, useStaleLive, useProject, useSegmentations, useTaskRuns, useTasks, type TaskEstimate, type TaskInfo, type TaskRunOutput, type TaskRunSummary } from '../../api'
import { Button, ConfirmInline, Progress, ProblemCard, RadioSeg, RunStatusBadge, fmtAgo, fmtDuration } from '../../lib'
import { openEditor, registry, toast, useWorkbench, type EditorProps, toastProblem } from '../../shell'
import { useLayout, useReviewer, useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { DerivedRootDialog, FolderBrowser } from '../import'
import { useExplorerFilter } from '../explorer'
import { showOutput } from '../jobs'
import { RADIOMICS_TASK } from './commands'
import { ACTIVE_RUN, STOPPING_RUN, runActions, selectionFor, type RunAction, type SelectionMode } from './model'
import { check, toSettings } from './schema'
import { SchemaForm } from './SchemaForm'
import { ItemPicker } from './ItemPicker'
import { GpuAvailability } from './GpuAvailability'
import './tasks.css'

const CONFIRM_ABOVE = 20

export interface TaskParams {
  taskId: string
  /** A finished run whose results the tab shows instead of the form (tasks with a results extension) */
  runId?: string | null
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="task-section">
      <h2>{title}</h2>
      {children}
    </section>
  )
}

export function RunRow({ pid, run }: { pid: string; run: TaskRunSummary }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const jobs = useJobs(pid).data ?? []
  const job = jobs.find((j) => j.job_id === run.job_id)
  const sharedPhase = run.execution?.phase_step === true && run.execution.shared_conversion_job === true
  const live = !sharedPhase && ACTIVE_RUN.includes(run.status) && job && job.status !== 'succeeded'
  const actions = runActions(run, registry.readOnly)
  const stale = useStaleLive()
  const fenced = run.execution?.phase_step === true || run.task.id === 'dicom.convert'
  const [pending, setPending] = useState(false)
  const control = async (action: RunAction) => {
    setPending(true)
    try {
      if (action === 'cancel') {
        if (fenced) await api.cancelTaskRun(pid, run.run_id, { expected_attempt: run.attempts })
        else await api.cancelTaskRun(pid, run.run_id)
      }
      else if (action === 'pause') await api.pauseTaskRun(pid, run.run_id)
      else if (action === 'archive') await api.archiveTaskRun(pid, run.run_id)
      else if (action === 'retry_failed') await api.retryFailedTaskRun(pid, run.run_id, { expected_attempt: run.attempts })
      else if (fenced) await api.resumeTaskRun(pid, run.run_id, { expected_attempt: run.attempts })
      else await api.resumeTaskRun(pid, run.run_id)
    } catch (e) {
      toastProblem(e)
    }
    await qc.invalidateQueries({ queryKey: keys.taskRuns(pid) })
    setPending(false)
  }
  const c = run.counts
  const hasResults = !!registry.taskExtensions.get(run.task.id)?.results && !ACTIVE_RUN.includes(run.status)
  return (
    <li className="task-run" data-status={run.status}>
      <div className="task-run-head">
        <RunStatusBadge status={run.status} />
        <span className="task-run-name" title={run.run_id}>{run.name}</span>
        <span className="muted ml-auto">{fmtAgo(run.created_at)}</span>
      </div>
      {live ? <Progress value={job.done} total={job.total || 1} label={t('progress.run')} stale={stale} /> : null}
      {live && !run.execution?.phase_step && job.eta_s != null ? <span className="muted">{t('tasks.eta', { eta: fmtDuration(job.eta_s) })}</span> : null}
      {run.status === 'waiting_for_runner' ? <p className="muted">{t('tasks.waitingUser')}</p> : null}
      {run.status === 'queued' ? <p className="muted">{t('tasks.queuedHelp')}</p> : null}
      {run.status === 'waiting_for_resources' ? <p className="muted">{t('tasks.resourcesHelp')}</p> : null}
      {STOPPING_RUN.includes(run.status) ? (
        <p className={run.status === 'cleanup_pending' ? 'field-error' : 'muted'} role="status">
          {t(run.execution?.phase_step && run.status === 'cleanup_pending' ? 'conv.phaseCleanup' : run.status === 'cleanup_pending' ? 'tasks.cleanupPendingHelp' : 'tasks.stoppingHelp')}
        </p>
      ) : null}
      <span className="muted num">{run.task.id === 'dicom.convert' ? t('conv.recoveryCounts', { complete: c?.ok ?? 0, failed: c?.failed ?? 0, pending: c?.pending ?? 0 }) : t('tasks.counts', { ok: c?.ok ?? 0, failed: c?.failed ?? 0, skipped: c?.skipped ?? 0, items: c?.items ?? 0 })}</span>
      {run.error ? <p className="field-error" role="alert">{run.error}</p> : null}
      <div className="task-run-actions">
        <Button className="btn btn-sm" onClick={() => showOutput({ id: `run.${run.run_id}`, label: run.name, kind: 'project-run', ref: run.run_id, project: pid })}>
          {t('tasks.showLog')}
        </Button>
        {hasResults ? (
          <Button className="btn btn-sm btn-primary" onClick={() => openEditor('task', { taskId: run.task.id, runId: run.run_id })}>
            {t('tasks.showResults')}
          </Button>
        ) : null}
        {actions.map((a) => {
          const button = (onClick: () => void) => (
            <Button key={a} className="btn btn-sm" disabled={pending || ((a === 'resume' || a === 'retry_failed') && fenced && run.execution?.cleanup_verified !== true)} reason={t(pending ? 'reason.working' : 'reason.cleanup')} onClick={onClick}>
              {t(a === 'retry_failed' ? 'conv.retryFailed' : a === 'resume' && run.status === 'completed_with_errors' && run.task.id !== 'dicom.convert' ? 'tasks.retryFailed' : `tasks.${a}`)}
            </Button>
          )
          return a === 'cancel'
            ? <ConfirmInline key={a} question={t('confirm.cancelRun')} confirm={t('common.yesCancel')} onConfirm={() => void control(a)} trigger={button} />
            : button(() => void control(a))
        })}
      </div>
      <Outputs pid={pid} run={run} />
    </li>
  )
}

/** Archived supervised runs stay listed on request, read-only, outputs reachable */
function ArchivedRuns({ pid, taskId }: { pid: string; taskId: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const archived = useArchivedTaskRuns(pid, open)
  const runs = (archived.data ?? []).filter((r) => r.task.id === taskId)
  return (
    <>
      <div className="task-run-actions">
        <button type="button" className="btn btn-sm" aria-expanded={open} onClick={() => setOpen(!open)}>
          {t(open ? 'tasks.hideArchived' : 'tasks.showArchived')}
        </button>
      </div>
      {open ? archived.isLoading ? <p className="muted">{t('common.loading')}</p> : runs.length ? <ul className="task-runs">{runs.map((r) => <RunRow key={r.run_id} pid={pid} run={r} />)}</ul> : <p className="muted">{t('tasks.noArchived')}</p> : null}
    </>
  )
}

function Outputs({ pid, run }: { pid: string; run: TaskRunSummary }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const project = useProject(pid).data
  const outputs = useQuery({ queryKey: keys.taskRunOutputs(pid, run.run_id), queryFn: () => api.taskRunOutputs(pid, run.run_id), enabled: !ACTIVE_RUN.includes(run.status) })
  const rows = (outputs.data ?? []).filter((o) => o.kind !== 'mask' && o.kind !== 'image' && o.kind !== 'sidecar')
  const volumes = (outputs.data ?? []).filter((o) => o.kind === 'mask' || o.kind === 'image').length
  if (!rows.length && !volumes) return null
  const activate = async (field: string, on: boolean) => {
    await api.setAnnotationSource(pid, field, on ? run.run_id : null)
    void qc.invalidateQueries({ queryKey: keys.project(pid) })
  }
  return (
    <ul className="task-outputs">
      {volumes ? <li className="muted">{t('tasks.out.volumes', { count: volumes })}</li> : null}
      {rows.map((o) => (
        <li key={`${o.kind}-${o.ref ?? o.seg_id ?? ''}`}>
          <Icon spec={codicon(o.kind === 'segmentation_set' ? 'layers' : o.kind === 'import' ? 'cloud-download' : o.kind === 'features' ? 'beaker' : 'tag')} />
          <span>{t(`tasks.out.${o.kind}`, { defaultValue: o.kind })}</span>
          <OutputLink pid={pid} run={run} o={o} />
          {o.kind === 'annotations'
            ? (o.detail ?? '').split(',').filter(Boolean).map((f) => {
                const on = project?.annotation_sources?.[f] === run.run_id
                return (
                  <button key={f} type="button" className="btn btn-sm" aria-pressed={on} onClick={() => void activate(f, !on)}>
                    {t(on ? 'tasks.deactivate' : 'tasks.activate', { field: f })}
                  </button>
                )
              })
            : null}
        </li>
      ))}
    </ul>
  )
}

/** An output by its name, as a link that opens it; the API path or id stays in the tooltip */
function OutputLink({ pid, run, o }: { pid: string; run: TaskRunSummary; o: TaskRunOutput }) {
  const { t } = useTranslation()
  const sets = useSegmentations(pid).data ?? []
  const raw = [o.seg_id, o.ref, o.detail].filter(Boolean).join(' · ')
  if (o.kind === 'segmentation_set' && o.seg_id) {
    const segId = o.seg_id
    const name = sets.find((x) => x.seg_id === segId)?.name || segId
    const show = () => {
      const v = useViewerSync.getState()
      v.set({ segChoice: { ...v.segChoice, [pid]: segId } })
      toast({ message: t('viewer.segShown', { set: name }) })
    }
    return <button type="button" className="link truncate" title={raw} onClick={show}>{name}</button>
  }
  if (o.kind === 'features') {
    // the features run of a radiomics task run (its dashboard); the id is in the output's API path
    const rid = /\/runs\/([^/]+)\/features/.exec(o.detail ?? '')?.[1] ?? run.run_id
    return <button type="button" className="link truncate" title={raw} onClick={() => openEditor('run', { runId: rid })}>{run.name}</button>
  }
  if (o.kind === 'import')
    return <button type="button" className="link truncate" title={raw} onClick={() => useLayout.getState().showView('project')}>{run.name}</button>
  return null
}

/** The viewer's scan or case as an explicit item list: frozen when picked, so later navigation
 *  never moves the selection */
function CurrentShortcuts({ pid, segId, needMask, onPick }: { pid: string; segId: string | null; needMask: boolean; onPick: (ids: string[]) => void }) {
  const { t } = useTranslation()
  const activeItem = useViewerSync((s) => s.activeItemId)
  const activeCase = useViewerSync((s) => s.activeCaseId)
  const kase = useCase(pid, activeCase)
  const caseIds = (kase.data?.items ?? [])
    .filter((it) => it.scope === 'complete' && (!needMask || (segId ? !!it.masks?.[segId] : Object.keys(it.masks ?? {}).length > 0)))
    .map((it) => it.item_id)
  if (!activeItem && !activeCase) return null
  return (
    <div className="task-run-actions">
      {activeItem ? <Button className="btn btn-sm" onClick={() => onPick([activeItem])}>{t('tasks.currentScan')}</Button> : null}
      {activeCase ? (
        <Button className="btn btn-sm" disabled={!caseIds.length} reason={t('tasks.caseNoItems')} onClick={() => onPick(caseIds)}>
          {t('tasks.currentCase', { count: caseIds.length })}
        </Button>
      ) : null}
    </div>
  )
}

/** A finished run's results, from the task's extension, in place of the form */
function RunResults({ pid, info, runId }: { pid: string; info: TaskInfo; runId: string }) {
  const { t } = useTranslation()
  const m = info.manifest
  const run = (useTaskRuns(pid).data ?? []).find((r) => r.run_id === runId)
  const Results = registry.taskExtensions.get(m.id)?.results
  const c = run?.counts
  return (
    <div className="task-tab">
      <div className="task-run-actions">
        <Button className="btn btn-sm" onClick={() => openEditor('task', { taskId: m.id, runId: null })}>
          <Icon spec={codicon('arrow-left')} />
          {t('tasks.backToTask', { title: m.title })}
        </Button>
      </div>
      <h1>{run?.name ?? t('tasks.runResults')}</h1>
      {run ? (
        <p className="task-run-head">
          <RunStatusBadge status={run.status} />
          <span className="muted">{fmtAgo(run.created_at)}</span>
          {run.reviewer ? <span className="muted">{t('tasks.byReviewer', { name: run.reviewer })}</span> : null}
          <span className="muted num">{t('tasks.counts', { ok: c?.ok ?? 0, failed: c?.failed ?? 0, skipped: c?.skipped ?? 0, items: c?.items ?? 0 })}</span>
        </p>
      ) : null}
      {run?.error ? <p className="field-error" role="alert">{run.error}</p> : null}
      {Results ? <Results pid={pid} runId={runId} /> : null}
    </div>
  )
}

function EstimateView({ est }: { est: TaskEstimate }) {
  const { t } = useTranslation()
  return (
    <div className="task-estimate">
      <span>{t('tasks.est.units', { n: est.n_units, skipped: est.n_skipped })}</span>
      {est.estimated_total_s != null ? <span>{t('tasks.est.time', { t: fmtDuration(est.estimated_total_s) })}</span> : null}
      {est.output_bytes ? <span>{t('tasks.est.size', { mb: (est.output_bytes / 1048576).toFixed(1) })}</span> : null}
      {est.sample_errors?.length ? <span className="field-error">{est.sample_errors.join('; ')}</span> : null}
    </div>
  )
}

function Body({ pid, info, hidden }: { pid: string; info: TaskInfo; hidden?: boolean }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const m = info.manifest
  const ext = registry.taskExtensions.get(m.id)
  const tasks = useTasks().data?.tasks ?? []
  const taskTitle = (id: string) => tasks.find((x) => x.manifest.id === id)?.manifest.title ?? id
  const explorer = useExplorerFilter()
  const sets = useSegmentations(pid).data ?? []
  const project = useProject(pid).data
  const reviewer = useReviewer((s) => s.name)
  const [mode, setMode] = useState<SelectionMode>('all')
  const [list, setList] = useState('')
  const [segId, setSegId] = useState<string | null>(null)
  const [source, setSource] = useState<string | null>(null)
  const [browse, setBrowse] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [estimate, setEstimate] = useState<{ est: TaskEstimate; selection: unknown; values: unknown } | null>(null)
  const [estimating, setEstimating] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [askDerived, setAskDerived] = useState(false)
  const runs = (useTaskRuns(pid).data ?? []).filter((r) => r.task.id === m.id)
  const readsMasks = !!m.requires?.seg
  const selection = useMemo(
    () => selectionFor(mode, explorer, list, { ...(readsMasks && segId ? { seg_id: segId } : {}), ...(m.input === 'source' ? { source } : {}) }),
    [mode, explorer, list, readsMasks, segId, m.input, source],
  )
  const settings = toSettings(values)
  const errors = check(m.settings_schema, values)
  const invalid = Object.keys(errors).length > 0
  const preflight = useQuery({
    queryKey: keys.taskPreflight(pid, m.id, { selection, settings }),
    queryFn: () => api.preflightTask(pid, m.id, selection, settings),
    enabled: m.input !== 'source' || !!source,
    retry: false,
  })
  const pre = preflight.data
  const runBlocked = invalid
    ? 'reason.fixSettings'
    : m.input === 'source' && !source
      ? 'reason.chooseSource'
      : preflight.isError
        ? 'reason.preflightFailed'
        : !pre
          ? 'reason.checking'
          : pre.n_ready === 0
            ? 'reason.nothingReady'
            : 'reason.working'
  const onAction = { choose_derived_root: () => setAskDerived(true), choose_source: () => setBrowse(null) }

  // a GPU task over many items runs for hours: ask once before starting it
  const heavy = m.resources?.gpu !== undefined && m.resources.gpu !== 'none' && (pre?.n_ready ?? 0) > CONFIRM_ABOVE
  const run = async () => {
    setError(null)
    setBusy(true)
    try {
      await api.startTaskRun(pid, { task_id: m.id, settings, selection }, reviewer || undefined)
      toast({ message: t('tasks.started', { title: m.title }), tone: 'ok' })
      void qc.invalidateQueries({ queryKey: keys.taskRuns(pid) })
      void qc.invalidateQueries({ queryKey: keys.jobs(pid) })
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  const doEstimate = async () => {
    setError(null)
    setEstimating(true)
    try {
      setEstimate({ est: await api.estimateTask(pid, m.id, selection, settings), selection, values })
    } catch (e) {
      setError(e)
    } finally {
      setEstimating(false)
    }
  }

  if (m.id === RADIOMICS_TASK)
    return (
      <div className="task-tab">
        <h1>{m.title}</h1>
        <p className="muted">{m.description}</p>
        <p className="muted">{t('tasks.radiomicsHere')}</p>
        <button type="button" className="btn btn-primary" onClick={() => openEditor('radiomics', {})}>{t('tasks.openRadiomics')}</button>
        <Section title={t('tasks.runs')}>
          <ul className="task-runs">{runs.map((r) => <RunRow key={r.run_id} pid={pid} run={r} />)}</ul>
        </Section>
      </div>
    )

  return (
    <div className="task-tab" hidden={hidden}>
      <h1>{m.title}</h1>
      <p className="muted">{m.description}</p>
      {!info.available ? <div className="error-card">{info.unavailable_reason}</div> : null}
      {m.runtime.type === 'external' && info.runner_online === false ? (
        <div className="card" role="note">
          <p>{t('tasks.noRunnerUser')}</p>
        </div>
      ) : null}

      <Section title={t('tasks.selection')}>
        {m.input === 'source' ? (
          <>
            <p className="muted">{t('tasks.sourceHelp')}</p>
            <p className="mono">{source ?? t('tasks.noSource')}</p>
            <FolderBrowser path={browse} onPath={(d) => { setBrowse(d); setSource(d) }} selected={source} onSelectFile={setSource} />
          </>
        ) : (
          <>
            <RadioSeg label={t('tasks.selection')} value={mode} options={(['all', 'explorer', 'list'] as SelectionMode[]).map((k) => ({ value: k, label: t(`tasks.mode.${k}`) }))} onChange={setMode} />
            {m.input === 'items' ? (
              <CurrentShortcuts
                pid={pid}
                segId={readsMasks ? (segId ?? project?.default_seg ?? null) : null}
                needMask={readsMasks}
                onPick={(ids) => {
                  setMode('list')
                  setList(ids.join('\n'))
                }}
              />
            ) : null}
            {mode === 'list' ? <ItemPicker pid={pid} value={list} onChange={setList} onBusyChange={setSelecting} /> : null}
            {readsMasks ? (
              <label className="field">
                <span className="field-label">{t('tasks.segSet')}</span>
                <select className="select" value={segId ?? project?.default_seg ?? ''} onChange={(e) => setSegId(e.target.value)}>
                  {sets.map((s) => <option key={s.seg_id} value={s.seg_id}>{s.name || s.seg_id}</option>)}
                </select>
              </label>
            ) : null}
          </>
        )}
      </Section>

      <Section title={t('tasks.settings')}>
        {m.runtime.type === 'external' && m.resources?.gpu && m.resources.gpu !== 'none' ? <GpuAvailability info={info} /> : null}
        {ext?.settings ? <ext.settings pid={pid} values={values} onChange={setValues} segId={segId} /> : <SchemaForm schema={m.settings_schema} values={values} errors={errors} showAllErrors={invalid} onChange={setValues} />}
      </Section>

      <Section title={t('tasks.preflight')}>
        {preflight.error ? <ProblemCard error={preflight.error} onAction={onAction} /> : null}
        {pre ? (
          <>
            <p>{t('tasks.ready', { ready: pre.n_ready, n: pre.n_selected })}</p>
            {Object.entries(pre.missing ?? {}).map(([reason, n]) => (
              <p key={reason} className="muted">{t('tasks.missing', { reason, n })}</p>
            ))}
            {(pre.suggestions ?? []).map((s) => (
              <button key={s.task_id + s.reason} type="button" className="btn btn-sm" title={s.task_id} onClick={() => openEditor('task', { taskId: s.task_id })}>
                {t('tasks.suggest', { task: taskTitle(s.task_id), reason: s.reason })}
              </button>
            ))}
            {pre.derived_root_required ? (
              <div className="error-card">
                {t('tasks.derivedNeeded')}
                <button type="button" className="btn btn-sm" onClick={() => setAskDerived(true)}>{t('problemAction.choose_derived_root')}</button>
              </div>
            ) : null}
          </>
        ) : null}
        {ext?.review ? <ext.review pid={pid} values={values} onChange={setValues} segId={segId ?? project?.default_seg ?? null} itemIds={pre?.ready_item_ids ?? null} /> : null}
        <div className="task-run-actions">
          <button type="button" className="btn" disabled={selecting || estimating} onClick={() => void doEstimate()}>{t(estimating ? 'tasks.estimating' : 'tasks.estimate')}</button>
          <ConfirmInline
            question={t('tasks.confirmRun', { n: pre?.n_ready ?? 0, title: m.title })}
            confirm={t('tasks.confirmStart')}
            keep={t('common.cancel')}
            onConfirm={() => void run()}
            trigger={(ask) => (
              <Button
                className="btn btn-primary"
                disabled={busy || selecting || !info.available || invalid || !pre || pre.n_ready === 0}
                reason={!info.available ? (info.unavailable_reason ?? t('reason.taskUnavailable')) : t(runBlocked)}
                onClick={() => (heavy ? ask() : void run())}
              >
                <Icon spec={codicon('play')} />
                {t('tasks.run')}
              </Button>
            )}
          />
        </div>
        {pre && pre.n_selected === 0 ? <p className="muted">{t(mode === 'list' ? 'tasks.listEmpty' : 'tasks.nothingSelected')}</p> : null}
        {estimate && estimate.selection === selection && estimate.values === values ? <EstimateView est={estimate.est} /> : null}
        {error ? <ProblemCard error={error} onAction={onAction} /> : null}
      </Section>

      <Section title={t('tasks.runs')}>
        {runs.length ? <ul className="task-runs">{runs.map((r) => <RunRow key={r.run_id} pid={pid} run={r} />)}</ul> : <p className="muted">{t('tasks.noRuns')}</p>}
        {info.manifest.resources?.gpu && info.manifest.resources.gpu !== 'none' ? <ArchivedRuns pid={pid} taskId={m.id} /> : null}
      </Section>
      {askDerived ? (
        <DerivedRootDialog
          pid={pid}
          onClose={(ok) => {
            setAskDerived(false)
            if (ok) void preflight.refetch()
          }}
        />
      ) : null}
    </div>
  )
}

function TaskEditor({ params, panelId }: EditorProps<TaskParams>) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, error, refetch } = useTasks()
  const info = data?.tasks.find((x) => x.manifest.id === params.taskId)
  // a tab restored before the task list loaded is named after the task id until now
  const title = info?.manifest.title
  useEffect(() => {
    if (!title) return
    const panel = useWorkbench.getState().dock?.getPanel(panelId)
    if (panel && panel.title !== title) panel.api.setTitle(title)
  }, [panelId, title])
  if (error) return <ProblemCard error={error} onRetry={() => void refetch()} />
  if (!data) return <div className="empty">{t('common.loading')}</div>
  if (!info) return <div className="error-card">{t('tasks.unknown', { id: params.taskId })}</div>
  // the run's results sit over the form, which keeps its draft (selection, settings, review)
  const showRun = !!params.runId && !!registry.taskExtensions.get(info.manifest.id)?.results
  return (
    <>
      {showRun && params.runId ? <RunResults pid={pid} info={info} runId={params.runId} /> : null}
      <Body pid={pid} info={info} hidden={showRun} />
    </>
  )
}

export default TaskEditor
