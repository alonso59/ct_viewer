// What the scheduler last said about a run: shared by the task's run list and the Jobs panel
import { useTranslation } from 'react-i18next'

import type { SchedulerStatus } from '../api'

/** The run's `execution.scheduler`, when the runner wrote one */
export function schedulerOf(execution: Record<string, unknown> | null | undefined): SchedulerStatus | null {
  const value = execution?.scheduler
  return value && typeof value === 'object' && typeof (value as SchedulerStatus).state === 'string' ? (value as SchedulerStatus) : null
}

export function SchedulerLine({ status }: { status: SchedulerStatus }) {
  const { t } = useTranslation()
  const parts = [
    status.job_id ? t('sched.job', { id: status.job_id }) : null,
    status.node ? t('sched.node', { node: status.node }) : null,
    status.elapsed && status.time_limit ? t('sched.time', { elapsed: status.elapsed, limit: status.time_limit }) : null,
    status.profile ? t('sched.profile', { name: status.profile }) : null,
  ].filter(Boolean)
  const done = status.accounting
  return (
    <div className="muted small" role="status" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span>
        {t('sched.state', { state: status.state })}
        {status.pending_reason ? ` (${t('sched.reason', { reason: status.pending_reason })})` : null}
        {parts.length ? ` · ${parts.join(' · ')}` : null}
      </span>
      {done ? <span>{t('sched.accounting', { state: done.state ?? '', elapsed: done.elapsed ?? '', code: done.exit_code ?? '' })}</span> : null}
      {status.efficiency ? (
        <details>
          <summary>{t('sched.efficiency')}</summary>
          <pre className="mono" style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>{status.efficiency}</pre>
        </details>
      ) : null}
    </div>
  )
}
