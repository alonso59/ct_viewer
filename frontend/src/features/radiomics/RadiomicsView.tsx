// Left pane Radiomics view: New run, runs with live progress, cancel/resume, errors and exports
// (RAD-06..10), and profiles (RAD-03).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, useJobs, useProfiles, useRadiomicsSchema, useRunControl, useRunErrors, useRuns, type Job } from '../../api'
import { Dialog, IconButton, Progress, fmtAgo, fmtDuration } from '../../lib'
import { openEditor, toast, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { errorMessage } from './errors'
import { ACTIVE, DONE, RESUMABLE, RUN_TONE, runProgress } from './runs'
import { fromWire } from './model/settings'
import type { RunSummary } from './model/types'
import { useDraft } from './store'

function ErrorsDialog({ pid, run, onClose }: { pid: string; run: RunSummary; onClose: () => void }) {
  const { t } = useTranslation()
  const errors = useRunErrors(pid, run.run_id)
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('rad.errorsTitle', { name: run.name })} icon={codicon('warning')} size="lg">
      {errors.isLoading ? <div className="muted">{t('common.loading')}</div> : null}
      {errors.error ? <div className="field-error">{errorMessage(errors.error, t('common.error'))}</div> : null}
      {errors.data?.length === 0 ? <div className="muted">{t('rad.noErrors')}</div> : null}
      {errors.data?.length ? (
        <table className="rad-errors">
          <thead>
            <tr>
              <th>{t('rad.errItem')}</th>
              <th>{t('rad.errLabel')}</th>
              <th>{t('rad.errKind')}</th>
              <th>{t('rad.errMessage')}</th>
            </tr>
          </thead>
          <tbody>
            {errors.data.map((e) => (
              <tr key={`${e.item_id}-${e.label}-${e.at}`}>
                <td className="mono">{e.item_id}</td>
                <td className="num">{e.label}</td>
                <td>{t(`rad.errKindName.${e.kind}`)}</td>
                <td>{e.error}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </Dialog>
  )
}

function RunRow({ pid, run, jobs, onErrors }: { pid: string; run: RunSummary; jobs: Job[]; onErrors: () => void }) {
  const { t } = useTranslation()
  const control = useRunControl(pid)
  const p = runProgress(run, jobs)
  const c = run.counts
  const act = (action: 'cancel' | 'resume') =>
    control.mutateAsync({ rid: run.run_id, action }).catch((e: unknown) => toast({ message: errorMessage(e, t('common.error')), tone: 'error' }))
  const done = DONE.includes(run.status)
  return (
    <li className="rad-run" data-status={run.status}>
      <div className="rad-run-head">
        <Icon spec={codicon('graph')} />
        {done ? (
          <button type="button" className="link rad-run-name" onClick={() => openEditor('run', { runId: run.run_id })}>{run.name}</button>
        ) : (
          <span className="rad-run-name">{run.name}</span>
        )}
        <span className="badge" data-tone={RUN_TONE[run.status]}>{t(`runStatus.${run.status}`)}</span>
      </div>
      <div className="muted rad-run-meta">
        <span>{t('rad.runCounts', { ok: c.ok, items: c.items, features: c.features })}</span>
        {c.failed ? <span className="field-error">{t('rad.runFailed', { count: c.failed })}</span> : null}
        {c.skipped ? <span className="field-warning">{t('rad.runSkipped', { count: c.skipped })}</span> : null}
      </div>
      <div className="muted rad-run-meta">{t('rad.runBy', { reviewer: run.reviewer, ago: fmtAgo(run.created_at) })}</div>
      {p ? (
        <div className="rad-run-progress" data-testid={`progress-${run.run_id}`}>
          <Progress value={p.done} total={p.total} />
          <span className="muted num">
            {p.eta !== null && p.eta > 0 ? t('rad.progressEta', { done: p.done, total: p.total, time: fmtDuration(p.eta) }) : t('rad.progress', { done: p.done, total: p.total })}
          </span>
        </div>
      ) : null}
      <div className="rad-run-actions">
        {ACTIVE.includes(run.status) ? <IconButton label={t('rad.cancel')} icon={codicon('debug-stop')} disabled={control.isPending} onClick={() => void act('cancel')} /> : null}
        {RESUMABLE.includes(run.status) ? <IconButton label={t('rad.resume')} icon={codicon('debug-continue')} disabled={control.isPending} onClick={() => void act('resume')} /> : null}
        {c.failed || c.skipped ? <IconButton label={t('rad.showErrors')} icon={codicon('warning')} onClick={onErrors} /> : null}
        {done ? (
          <>
            <a className="icon-btn" href={api.runExportUrl(pid, run.run_id, 'csv', 'long')} download aria-label={t('rad.exportLong')} title={t('rad.exportLong')}>
              <Icon spec={codicon('cloud-download')} />
            </a>
            <a className="icon-btn" href={api.runExportUrl(pid, run.run_id, 'csv', 'wide')} download aria-label={t('rad.exportWide')} title={t('rad.exportWide')}>
              <Icon spec={codicon('table')} />
            </a>
          </>
        ) : null}
      </div>
    </li>
  )
}

export function RadiomicsView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const runs = useRuns(pid)
  const profiles = useProfiles(pid)
  const schema = useRadiomicsSchema()
  const jobs = useJobs(pid).data ?? []
  const [errorsOf, setErrorsOf] = useState<RunSummary | null>(null)
  const list = [...(runs.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))
  return (
    <div className="rad-view">
      <div className="rad-view-pad">
        <button type="button" className="btn btn-primary rad-view-new" onClick={() => openEditor('radiomics', {})}>
          <Icon spec={codicon('add')} />
          {t('rad.newRun')}
        </button>
      </div>
      <div>
        <div className="section-title">{t('rad.runs')}</div>
        {runs.isLoading ? <div className="muted rad-view-pad">{t('common.loading')}</div> : null}
        {runs.error ? <div className="field-error rad-view-pad">{errorMessage(runs.error, t('common.error'))}</div> : null}
        {runs.isSuccess && list.length === 0 ? <div className="muted rad-view-pad">{t('rad.noRuns')}</div> : null}
        <ul className="rad-runs" aria-label={t('rad.runs')}>
          {list.map((r) => (
            <RunRow key={r.run_id} pid={pid} run={r} jobs={jobs} onErrors={() => setErrorsOf(r)} />
          ))}
        </ul>
      </div>
      <div>
        <div className="section-title">{t('rad.profiles')}</div>
        {profiles.isSuccess && profiles.data.length === 0 ? <div className="muted rad-view-pad">{t('rad.noProfiles')}</div> : null}
        {(profiles.data ?? []).map((p) => (
          <button
            key={p.profile_hash}
            type="button"
            className="list-row"
            disabled={!schema.data}
            title={t('rad.loadIntoForm')}
            onClick={() => {
              if (!schema.data) return
              useDraft.getState().load(pid, fromWire(schema.data, p.settings), p.name)
              openEditor('radiomics', {})
            }}
          >
            <Icon spec={codicon('symbol-namespace')} />
            <span>{p.name}</span>
            <span className="muted mono rad-hash">{p.profile_hash.replace(/^sha256:/, '').slice(0, 8)}</span>
          </button>
        ))}
      </div>
      {errorsOf ? <ErrorsDialog pid={pid} run={errorsOf} onClose={() => setErrorsOf(null)} /> : null}
    </div>
  )
}
