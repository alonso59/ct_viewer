// Left pane Radiomics view: New run, profiles, runs (RAD-03, RAD-06)
import { useTranslation } from 'react-i18next'

import { useJobs, useProfiles, useRuns, type RadiomicsRun } from '../../api'
import { Progress, fmtAgo } from '../../lib'
import { openEditor, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'

export const RUN_TONE: Record<RadiomicsRun['status'], string | undefined> = {
  queued: undefined,
  running: 'accent',
  completed: 'ok',
  completed_with_errors: 'warn',
  failed: 'error',
  cancelled: undefined,
  interrupted: 'warn',
}

export function RadiomicsView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const runs = useRuns(pid).data ?? []
  const profiles = useProfiles(pid).data ?? []
  const jobs = useJobs().data ?? []
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '0 0 12px' }}>
      <div style={{ padding: '0 12px' }}>
        <button type="button" className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} onClick={() => openEditor('radiomics', {})}>
          <Icon spec={codicon('add')} />
          {t('radiomics.newRun')}
        </button>
      </div>
      <div>
        <div className="section-title">{t('radiomics.runs')}</div>
        {runs.length === 0 ? <div className="muted" style={{ padding: '0 12px' }}>{t('radiomics.noRuns')}</div> : null}
        {runs.map((r) => {
          const job = jobs.find((j) => j.ref === r.run_id && j.status === 'running')
          return (
            <button key={r.run_id} type="button" className="list-row" style={{ minHeight: 40, flexDirection: 'column', alignItems: 'stretch', gap: 2, padding: '4px 12px' }} onClick={() => r.status !== 'running' && openEditor('run', { runId: r.run_id })}>
              <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <Icon spec={codicon('graph')} />
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.name}</span>
                <span className="badge" data-tone={RUN_TONE[r.status]}>{t(`runStatus.${r.status}`)}</span>
              </span>
              <span className="muted" style={{ fontSize: 'var(--fs-badge)' }}>
                {t('radiomics.runMeta', { items: r.counts.items, features: r.counts.features, ago: fmtAgo(r.created_at) })}
              </span>
              {job ? <Progress value={job.done} total={job.total} /> : null}
            </button>
          )
        })}
      </div>
      <div>
        <div className="section-title">{t('radiomics.profiles')}</div>
        {profiles.map((p) => (
          <div key={p.name} className="list-row" style={{ cursor: 'default' }}>
            <Icon spec={codicon('symbol-namespace')} />
            <span>{p.name}</span>
            <span className="muted mono" style={{ marginLeft: 'auto', fontSize: 'var(--fs-badge)' }}>{p.hash}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
