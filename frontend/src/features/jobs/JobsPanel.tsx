// Jobs panel (API-41, BE-06) and Output log (server events, newest last)
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { create } from 'zustand'

import i18n from '../../i18n'
import { useCancelJob, useJobs, type ServerEvent } from '../../api'
import { Progress, RunStatusBadge, fmtDuration, runStatusKey } from '../../lib'
import { useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { Icon, codicon } from '../../theme'

interface LogState {
  lines: { at: string; text: string; tone?: 'ok' | 'warn' | 'error' }[]
  push: (text: string, tone?: 'ok' | 'warn' | 'error') => void
}
export const useOutput = create<LogState>()((set) => ({
  lines: [],
  push: (text, tone) => set((s) => ({ lines: [...s.lines.slice(-499), { at: new Date().toISOString().slice(11, 19), text, tone }] })),
}))

export function logEvent(e: ServerEvent) {
  const push = useOutput.getState().push
  const t = i18n.t.bind(i18n)
  if (e.event === 'curation.appended')
    push(t('output.curation', { reviewer: e.data.reviewer, id: e.data.item_id ?? e.data.case_id, target: e.data.target, status: e.data.status }))
  if (e.event === 'job.finished')
    push(t('output.job', { title: t(`jobs.kind.${e.data.kind}`), status: t(runStatusKey(e.data.status)) }), e.data.status === 'succeeded' ? 'ok' : 'warn')
  if (e.event === 'index.rebuilt') push(t('output.index', { items: e.data.n_items, warnings: e.data.n_warnings }), 'ok')
  if (e.event === 'project.updated') push(t('output.project', { fields: e.data.fields.join(', ') }))
}

export function JobsPanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const jobs = useJobs(pid).data ?? []
  const cancel = useCancelJob(pid)
  if (!jobs.length) return <div className="empty">{t('jobs.none')}</div>
  return (
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
            <td>{t(`jobs.kind.${j.kind}`)}</td>
            <td><RunStatusBadge status={j.status} title={j.error ?? undefined} /></td>
            <td>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1 }}><Progress value={j.done} total={j.total} /></div>
                <span className="num muted">{t('jobs.count', { done: j.done, total: j.total })}</span>
              </div>
            </td>
            <td className="num muted">{j.status === 'running' && j.eta_s !== null ? fmtDuration(j.eta_s) : ''}</td>
            <td>
              {j.status === 'running' ? (
                <button type="button" className="btn btn-sm" onClick={() => cancel.mutate(j.job_id)}>
                  <Icon spec={codicon('debug-stop')} />
                  {t('common.cancel')}
                </button>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function OutputPanel() {
  const { t } = useTranslation()
  const lines = useOutput((s) => s.lines)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => end.current?.scrollIntoView({ block: 'end' }), [lines.length])
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

export function JobStatus() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid)
  const running = (useJobs(pid).data ?? []).filter((j) => j.status === 'running')
  if (!running.length) return null
  const j = running[0]
  if (!j) return null
  const title = t(`jobs.kind.${j.kind}`)
  return (
    <button type="button" className="statusbar-item" onClick={() => useLayout.getState().showPanelTab('jobs')} title={title}>
      <Icon spec={codicon('sync')} className="codicon-modifier-spin" />
      {t('status.job', { title, done: j.done, total: j.total })}
    </button>
  )
}

export function useJobsBadge(): number | null {
  const pid = useWorkbench((s) => s.pid)
  return (useJobs(pid).data ?? []).filter((j) => j.status === 'running').length || null
}
