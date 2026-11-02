import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { create } from 'zustand'

import i18n from '../../i18n'
import { useCancelJob, useJobs, useStaleLive, type Job, type ServerEvent } from '../../api'
import { ConfirmInline, Progress, RunStatusBadge, fmtDuration, runStatusKey } from '../../lib'
import { useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { Icon, codicon } from '../../theme'

/** Every job kind has a label: a new server kind fails typecheck, never shows a raw key */
export const JOB_KIND: Record<Job['kind'], string> = {
  index: 'jobs.kind.index',
  hash: 'jobs.kind.hash',
  thumbnail: 'jobs.kind.thumbnail',
  radiomics: 'jobs.kind.radiomics',
  mesh: 'jobs.kind.mesh',
  task: 'jobs.kind.task',
  'open-convert': 'jobs.kind.open-convert',
}

interface LogState {
  lines: { at: string; text: string; tone?: 'ok' | 'warn' | 'error' }[]
  push: (text: string, tone?: 'ok' | 'warn' | 'error') => void
}
const useOutput = create<LogState>()((set) => ({
  lines: [],
  push: (text, tone) => set((s) => ({ lines: [...s.lines.slice(-499), { at: new Date().toISOString().slice(11, 19), text, tone }] })),
}))

export function logEvent(e: ServerEvent) {
  const push = useOutput.getState().push
  const t = i18n.t.bind(i18n)
  if (e.event === 'curation.appended')
    push(t('output.curation', { reviewer: e.data.reviewer, id: e.data.item_id ?? e.data.case_id, target: e.data.target, status: e.data.status }))
  if (e.event === 'job.finished')
    push(t('output.job', { title: t(JOB_KIND[e.data.kind as Job['kind']] ?? 'jobs.kind.task'), status: t(runStatusKey(e.data.status)) }), e.data.status === 'succeeded' ? 'ok' : 'warn')
  if (e.event === 'index.rebuilt') push(t('output.index', { items: e.data.n_items, warnings: e.data.n_warnings }), 'ok')
  if (e.event === 'project.updated') push(t('output.project', { fields: e.data.fields.join(', ') }))
}

export function JobsPanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const jobs = useJobs(pid).data ?? []
  const cancel = useCancelJob(pid)
  const stale = useStaleLive()
  if (!jobs.length) return <div className="empty">{t('jobs.none')}</div>
  return (
    <>
    {stale ? <p className="muted jobs-stale" role="status">{t('jobs.stale')}</p> : null}
    <table className="table">
      <thead>
        <tr>
          <th>{t('jobs.col.job')}</th>
          <th>{t('jobs.col.status')}</th>
          <th style={{ width: '30%' }}>{t('jobs.col.progress')}</th>
          <th className="num">{t('jobs.col.eta')}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {jobs.map((j) => (
          <tr key={j.job_id}>
            <td>{t(JOB_KIND[j.kind])}</td>
            <td><RunStatusBadge status={j.status} title={j.error ?? undefined} />{j.error ? <p className="field-error">{j.error}</p> : null}</td>
            <td>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1 }}><Progress value={j.done} total={j.total} label={t(JOB_KIND[j.kind])} stale={stale} /></div>
                <span className="num muted">{t('jobs.count', { done: j.done, total: j.total })}</span>
              </div>
            </td>
            <td className="num muted">{j.status === 'running' && j.eta_s !== null ? fmtDuration(j.eta_s) : ''}</td>
            <td>
              {j.status === 'running' || (j.status === 'queued' && j.kind !== 'task') ? (
                <ConfirmInline
                  question={t('confirm.cancelJob')}
                  confirm={t('common.yesCancel')}
                  onConfirm={() => cancel.mutate(j.job_id)}
                  trigger={(ask) => (
                    <button type="button" className="btn btn-sm" onClick={ask}>
                      <Icon spec={codicon('debug-stop')} />
                      {t('common.cancel')}
                    </button>
                  )}
                />
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </>
  )
}

/** The Output tab's Activity channel: this session's server events */
export function ActivityLog() {
  const { t } = useTranslation()
  const lines = useOutput((s) => s.lines)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [lines.length])
  if (!lines.length) return <div className="empty">{t('output.empty')}</div>
  return (
    <div className="mono" style={{ fontSize: 'var(--fs-panel)', padding: '4px 12px', whiteSpace: 'pre-wrap' }}>
      {lines.map((l, i) => (
        <div key={i} style={{ color: l.tone ? `var(--${l.tone})` : undefined }}>
          <span className="muted">{l.at}</span> {l.text}
        </div>
      ))}
      <div ref={end} />
    </div>
  )
}

/** Background work that is not finished, by state */
function activeJobs(jobs: Job[]) {
  return {
    running: jobs.filter((j) => j.status === 'running'),
    queued: jobs.filter((j) => j.status === 'queued'),
    waiting: jobs.filter((j) => j.status === 'waiting_for_runner'),
  }
}

/** One running job reads with its progress; more work reads as counts ("1 running · 2 queued") */
export function JobStatus() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid)
  const { running, queued, waiting } = activeJobs(useJobs(pid).data ?? [])
  const j = running[0]
  if (!j && !queued.length && !waiting.length) return null
  const single = j && running.length === 1 && !queued.length && !waiting.length
  const label = single
    ? t('status.job', { title: t(JOB_KIND[j.kind]), done: j.done, total: j.total })
    : [
        running.length ? t('status.jobsRunning', { count: running.length }) : '',
        queued.length ? t('status.jobsQueued', { count: queued.length }) : '',
        waiting.length ? t('status.jobsWaiting', { count: waiting.length }) : '',
      ].filter(Boolean).join(' · ')
  return (
    <button type="button" className="statusbar-item" onClick={() => useLayout.getState().showPanelTab('jobs')} title={t('status.jobsHelp')}>
      <Icon spec={codicon('sync')} className={running.length ? 'codicon-modifier-spin' : undefined} />
      {label}
    </button>
  )
}

export function useJobsBadge(): number | null {
  const pid = useWorkbench((s) => s.pid)
  const { running, queued, waiting } = activeJobs(useJobs(pid).data ?? [])
  return running.length + queued.length + waiting.length || null
}
