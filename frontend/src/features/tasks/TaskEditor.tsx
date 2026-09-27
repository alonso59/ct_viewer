// One tab per task (UI-20): Selection · Settings (schema form) · Preflight/Estimate · Run, then its
// runs with their outputs (a segmentation set, an import, annotations or a features run).
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, useJobs, useProject, useSegmentations, useTaskRuns, useTasks, type TaskEstimate, type TaskInfo, type TaskRunOutput, type TaskRunSummary } from '../../api'
import { Progress, ProblemCard, RunStatusBadge, fmtAgo, fmtDuration } from '../../lib'
import { openEditor, toast, useWorkbench, type EditorProps } from '../../shell'
import { useLayout, useReviewer, useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { DerivedRootDialog, FolderBrowser } from '../import'
import { useExplorerFilter } from '../explorer'
import { ACTIVE_RUN, RESUMABLE_RUN, selectionFor, type SelectionMode } from './model'
import { check, toSettings } from './schema'
import { SchemaForm } from './SchemaForm'
import './tasks.css'

export interface TaskParams {
  taskId: string
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
  const live = ACTIVE_RUN.includes(run.status) && job && job.status !== 'succeeded'
  const control = async (action: 'cancel' | 'resume') => {
    try {
      if (action === 'cancel') await api.cancelTaskRun(pid, run.run_id)
      else await api.resumeTaskRun(pid, run.run_id)
    } catch (e) {
      toast({ message: e instanceof Error ? e.message : String(e), tone: 'error' })
    }
    void qc.invalidateQueries({ queryKey: keys.taskRuns(pid) })
  }
  const c = run.counts
  return (
    <li className="task-run" data-status={run.status}>
      <div className="task-run-head">
        <RunStatusBadge status={run.status} />
        <span className="task-run-name" title={run.run_id}>{run.name}</span>
        <span className="muted ml-auto">{fmtAgo(run.created_at)}</span>
      </div>
      {live ? <Progress value={job.done} total={job.total || 1} /> : null}
      {live && job.eta_s != null ? <span className="muted">{t('tasks.eta', { eta: fmtDuration(job.eta_s) })}</span> : null}
      {run.status === 'waiting_for_runner' ? <p className="muted">{t('tasks.waitingHelp')}</p> : null}
      <span className="muted num">{t('tasks.counts', { ok: c?.ok ?? 0, failed: c?.failed ?? 0, skipped: c?.skipped ?? 0, items: c?.items ?? 0 })}</span>
      {run.error ? <span className="field-error">{run.error}</span> : null}
      <div className="task-run-actions">
        {ACTIVE_RUN.includes(run.status) ? <button type="button" className="btn btn-sm" onClick={() => void control('cancel')}>{t('common.cancel')}</button> : null}
        {RESUMABLE_RUN.includes(run.status) && run.task.id !== 'radiomics.pyradiomics' ? (
          <button type="button" className="btn btn-sm" onClick={() => void control('resume')}>{t('tasks.resume')}</button>
        ) : null}
      </div>
      <Outputs pid={pid} run={run} />
    </li>
  )
}

/** TSK-09 outputs; annotation runs can be activated per field (ANZ-04) */
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

/** TSK-09 (AUD-A3-09): an output by its name, as a link that opens it; the API path or id stays in
 *  the tooltip (never on screen) */
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

function Body({ pid, info }: { pid: string; info: TaskInfo }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const m = info.manifest
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
  const [estimate, setEstimate] = useState<TaskEstimate | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [askDerived, setAskDerived] = useState(false)
  const runs = (useTaskRuns(pid).data ?? []).filter((r) => r.task.id === m.id)
  const readsMasks = !!m.requires?.seg
  const selection = useMemo(
    () => selectionFor(mode, explorer, list, { ...(readsMasks && segId ? { seg_id: segId } : {}), ...(m.input === 'source' ? { source } : {}) }),
    [mode, explorer, list, readsMasks, segId, m.input, source],
  )
  const settings = toSettings(values)
  const errors = check(m.settings_schema, values)
  const preflight = useQuery({
    queryKey: keys.taskPreflight(pid, m.id, selection),
    queryFn: () => api.preflightTask(pid, m.id, selection, settings),
    enabled: m.input !== 'source' || !!source,
    retry: false,
  })
  const pre = preflight.data
  const onAction = { choose_derived_root: () => setAskDerived(true), choose_source: () => setBrowse(null) }

  const run = async () => {
    setError(null)
    setBusy(true)
    try {
      const r = await api.startTaskRun(pid, { task_id: m.id, settings, selection }, reviewer || undefined)
      toast({ message: t('tasks.started', { title: m.title }), tone: 'ok' })
      void qc.invalidateQueries({ queryKey: keys.taskRuns(pid) })
      void qc.invalidateQueries({ queryKey: keys.jobs(pid) })
      return r
    } catch (e) {
      setError(e)
      return null
    } finally {
      setBusy(false)
    }
  }
  const doEstimate = async () => {
    setError(null)
    try {
      setEstimate(await api.estimateTask(pid, m.id, selection, settings))
    } catch (e) {
      setError(e)
    }
  }

  if (m.id === 'radiomics.pyradiomics')
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
    <div className="task-tab">
      <h1>{m.title}</h1>
      <p className="muted">{m.description}</p>
      {!info.available ? <div className="error-card">{info.unavailable_reason}</div> : null}
      {m.runtime.type === 'external' && info.runner_online === false ? <div className="error-card">{t('tasks.noRunner', { hint: m.runtime.env_hint ?? '' })}</div> : null}

      <Section title={t('tasks.selection')}>
        {m.input === 'source' ? (
          <>
            <p className="muted">{t('tasks.sourceHelp')}</p>
            <p className="mono">{source ?? t('tasks.noSource')}</p>
            <FolderBrowser path={browse} onPath={(d) => { setBrowse(d); setSource(d) }} selected={source} onSelectFile={setSource} />
          </>
        ) : (
          <>
            <div className="seg" role="radiogroup" aria-label={t('tasks.selection')}>
              {(['all', 'explorer', 'list'] as SelectionMode[]).map((k) => (
                <button key={k} type="button" role="radio" aria-checked={mode === k} aria-pressed={mode === k} onClick={() => setMode(k)}>
                  {t(`tasks.mode.${k}`)}
                </button>
              ))}
            </div>
            {mode === 'list' ? <textarea className="input mono" rows={3} value={list} placeholder={t('tasks.listHelp')} onChange={(e) => setList(e.target.value)} /> : null}
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
        <SchemaForm schema={m.settings_schema} values={values} errors={errors} onChange={setValues} />
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
              <button key={s.task_id + s.reason} type="button" className="btn btn-sm" onClick={() => openEditor('task', { taskId: s.task_id })}>
                {t('tasks.suggest', { task: s.task_id, reason: s.reason })}
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
        <div className="task-run-actions">
          <button type="button" className="btn" onClick={() => void doEstimate()}>{t('tasks.estimate')}</button>
          <button type="button" className="btn btn-primary" disabled={busy || !info.available || Object.keys(errors).length > 0 || (pre ? pre.n_ready === 0 : true)} onClick={() => void run()}>
            <Icon spec={codicon('play')} />
            {t('tasks.run')}
          </button>
        </div>
        {estimate ? <EstimateView est={estimate} /> : null}
        {error ? <ProblemCard error={error} onAction={onAction} /> : null}
      </Section>

      <Section title={t('tasks.runs')}>
        {runs.length ? <ul className="task-runs">{runs.map((r) => <RunRow key={r.run_id} pid={pid} run={r} />)}</ul> : <p className="muted">{t('tasks.noRuns')}</p>}
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

export function TaskEditor({ params }: EditorProps<TaskParams>) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, error } = useTasks()
  const info = data?.tasks.find((x) => x.manifest.id === params.taskId)
  if (error) return <ProblemCard error={error} />
  if (!data) return <div className="empty">{t('common.loading')}</div>
  if (!info) return <div className="error-card">{t('tasks.unknown', { id: params.taskId })}</div>
  return <Body pid={pid} info={info} />
}

export default TaskEditor
