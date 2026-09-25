// Converter overlay window (UI-25, DCM-14, TSK-13): source → settings → dry run → run → result.
// Without a project the output is a write-once workspace dataset (`{derived}/_datasets/{name}/`)
// with Open / Create project / Add to project; inside a project it can convert into it instead.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import {
  api,
  useProject,
  useProjects,
  useTaskRun,
  useTasks,
  useWorkspaceRun,
  type TaskEstimate,
} from '../../api'
import { DerivedRootDialog, FolderBrowser, useImportWizard } from '../../features/import'
import { openPath } from '../../features/open/navigate'
import { NewProjectDialog } from '../../features/projects'
import { Dialog, ProblemCard, Progress } from '../../lib'
import { codicon } from '../../theme'
import { defaultDatasetName, useConverter } from './store'
import './converter.css'

const STEPS = ['source', 'settings', 'estimate', 'run', 'result'] as const
type Step = (typeof STEPS)[number]
type Target = 'project' | 'dataset'

interface Settings {
  target_profile: string
  phase_analyzer: boolean
  anonymize: 'none' | 'basic'
  name: string
}

const parent = (p: string) => p.replace(/\/[^/]*$/, '') || '/'
const fmtBytes = (n: number | null | undefined) => (n == null ? '—' : n > 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`)

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

function ProjectRunProgress({ pid, rid, onDone }: { pid: string; rid: string; onDone: () => void }) {
  const { t } = useTranslation()
  const run = useTaskRun(pid, rid).data
  const done = run && !['queued', 'running', 'waiting_for_runner'].includes(run.status)
  return (
    <div className="conv-body">
      <Progress value={run?.progress?.done ?? 0} total={run?.progress?.total || 1} />
      <p className="muted">{t(`conv.status.${done ? run.status : 'running'}`, { defaultValue: run?.status ?? '' })}</p>
      {run?.error ? <div className="error-card">{run.error}</div> : null}
      {done ? <button type="button" className="btn btn-primary" onClick={onDone}>{t('conv.showResult')}</button> : null}
    </div>
  )
}

export default function ConverterOverlay() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { source: initial, pid, close } = useConverter()
  const project = useProject(pid ?? '').data
  const manifest = useTasks().data?.tasks.find((x) => x.manifest.id === 'dicom.convert')?.manifest
  const profiles = ((manifest?.settings_schema?.properties as Record<string, { enum?: string[] }> | undefined)?.target_profile?.enum ?? ['generic']) as string[]
  const [step, setStep] = useState<Step>(initial ? 'settings' : 'source')
  const [browse, setBrowse] = useState<string | null>(initial ? parent(initial) : null)
  const [source, setSource] = useState<string | null>(initial)
  const [target, setTarget] = useState<Target>(pid ? 'project' : 'dataset')
  const [settings, setSettings] = useState<Settings>({ target_profile: 'generic', phase_analyzer: true, anonymize: 'none', name: defaultDatasetName() })
  const [estimate, setEstimate] = useState<TaskEstimate | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [run, setRun] = useState<{ kind: Target; rid: string } | null>(null)
  const [creating, setCreating] = useState(false)
  const [derivedPrompt, setDerivedPrompt] = useState(false)
  const [addTo, setAddTo] = useState('')
  const projects = useProjects().data ?? []
  const ws = useWorkspaceRun(run?.kind === 'dataset' ? run.rid : null).data
  const intoProject = target === 'project' && !!pid
  const needsDerived = intoProject && !!project && !project.path_roots.some((r) => r.role === 'derived')
  const taskSettings = { target_profile: settings.target_profile, phase_analyzer: settings.phase_analyzer, anonymize: settings.anonymize }

  const guard = async (fn: () => Promise<void>) => {
    setError(null)
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  const dryRun = () =>
    guard(async () => {
      if (!source) return
      const sel = { source }
      setEstimate(intoProject && pid ? await api.estimateTask(pid, 'dicom.convert', sel, taskSettings) : await api.estimateWorkspaceTask('dicom.convert', sel, taskSettings))
      setStep('estimate')
    })
  const start = () =>
    guard(async () => {
      if (!source) return
      const selection = { source }
      if (intoProject && pid) {
        const r = await api.startTaskRun(pid, { task_id: 'dicom.convert', settings: taskSettings, selection })
        setRun({ kind: 'project', rid: r.run_id })
      } else {
        const r = await api.startWorkspaceRun({ task_id: 'dicom.convert', settings: taskSettings, selection, name: settings.name.trim() || null })
        setRun({ kind: 'dataset', rid: r.run_id })
      }
      setStep('run')
    })
  const wsDone = ws && !['queued', 'running'].includes(ws.status)
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
    <Dialog open onOpenChange={(o) => !o && close()} title={t('conv.title')} icon={codicon('file-binary')} size="lg">
      <div className="conv">
        <StepBar step={step} />
        {step === 'source' ? (
          <div className="conv-body">
            <p className="muted">{t('conv.sourceHelp')}</p>
            <FolderBrowser path={browse} onPath={(p) => { setBrowse(p); setSource(p) }} selected={source} onSelectFile={(p) => setSource(p)} />
            <div className="conv-row">
              <span className="mono conv-path">{source ?? t('conv.noSource')}</span>
              <button type="button" className="btn btn-primary" disabled={!source} onClick={() => { setSettings((s) => ({ ...s, name: s.name || defaultDatasetName() })); setStep('settings') }}>{t('conv.next')}</button>
            </div>
          </div>
        ) : null}
        {step === 'settings' ? (
          <div className="conv-body">
            <div className="conv-row"><span className="muted">{t('conv.source')}</span><span className="mono conv-path">{source}</span><button type="button" className="btn btn-sm" onClick={() => setStep('source')}>{t('conv.change')}</button></div>
            {pid ? (
              <div className="field">
                <span className="field-label">{t('conv.output')}</span>
                <div className="seg" role="group">
                  <button type="button" aria-pressed={target === 'project'} onClick={() => setTarget('project')}>{t('conv.intoProject', { name: project?.name ?? '' })}</button>
                  <button type="button" aria-pressed={target === 'dataset'} onClick={() => setTarget('dataset')}>{t('conv.asDataset')}</button>
                </div>
              </div>
            ) : null}
            {target === 'dataset' ? (
              <label className="field">
                <span className="field-label">{t('conv.name')}</span>
                <input className="input" value={settings.name} onChange={(e) => setSettings({ ...settings, name: e.target.value })} />
                <span className="muted conv-help">{t('conv.nameHelp')}</span>
              </label>
            ) : null}
            <label className="field">
              <span className="field-label">{t('conv.profile')}</span>
              <select className="input" value={settings.target_profile} onChange={(e) => setSettings({ ...settings, target_profile: e.target.value })}>
                {profiles.map((p) => <option key={p} value={p}>{t(`conv.profiles.${p}`, { defaultValue: p })}</option>)}
              </select>
              <span className="muted conv-help">{t('conv.profileHelp')}</span>
            </label>
            <label className="conv-check">
              <input type="checkbox" checked={settings.phase_analyzer} onChange={(e) => setSettings({ ...settings, phase_analyzer: e.target.checked })} />
              {t('conv.phase')}
            </label>
            <label className="conv-check">
              <input type="checkbox" checked={settings.anonymize === 'basic'} onChange={(e) => setSettings({ ...settings, anonymize: e.target.checked ? 'basic' : 'none' })} />
              {t('conv.anonymize')}
            </label>
            <p className="muted conv-help">{t('conv.phiNotice')}</p>
            {needsDerived ? (
              <div className="error-card">
                {t('conv.needsDerived')} <button type="button" className="btn btn-sm" onClick={() => setDerivedPrompt(true)}>{t('conv.chooseDerived')}</button>
              </div>
            ) : null}
            <div className="conv-row conv-actions">
              <button type="button" className="btn btn-primary" disabled={busy || needsDerived} onClick={() => void dryRun()}>{t(busy ? 'conv.scanning' : 'conv.dryRun')}</button>
            </div>
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
            {estimate.sample_errors?.length ? <div className="error-card">{estimate.sample_errors.join('; ')}</div> : null}
            <div className="conv-row conv-actions">
              <button type="button" className="btn" onClick={() => setStep('settings')}>{t('conv.back')}</button>
              <button type="button" className="btn btn-primary" disabled={busy || estimate.n_units === 0} onClick={() => void start()}>{t('conv.run', { n: estimate.n_units })}</button>
            </div>
          </div>
        ) : null}
        {step === 'run' && run?.kind === 'project' && pid ? <ProjectRunProgress pid={pid} rid={run.rid} onDone={() => setStep('result')} /> : null}
        {step === 'run' && run?.kind === 'dataset' ? (
          <div className="conv-body">
            <Progress value={ws?.progress?.done ?? 0} total={ws?.progress?.total || 1} />
            <p className="muted">{t(`conv.status.${wsDone ? ws.status : 'running'}`, { defaultValue: ws?.status ?? '' })}</p>
            {ws?.error ? <div className="error-card">{ws.error}</div> : null}
            {wsDone ? <button type="button" className="btn btn-primary" onClick={() => setStep('result')}>{t('conv.showResult')}</button> : null}
          </div>
        ) : null}
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
        {error ? <ProblemCard error={error} /> : null}
      </div>
      {derivedPrompt && pid ? <DerivedRootDialog pid={pid} onClose={() => setDerivedPrompt(false)} /> : null}
    </Dialog>
  )
}
