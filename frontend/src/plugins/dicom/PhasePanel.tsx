import { useTranslation } from 'react-i18next'

import { isTaskRunPending, type SourceOperation } from '../../api'
import { Progress, RunStatusBadge } from '../../lib'

export function PhasePanel({ phase, busy, onControl }: { phase: NonNullable<SourceOperation['phase_run']>; busy: boolean; onControl: (action: 'resume' | 'cancel') => void }) {
  const { t } = useTranslation()
  const progress = phase.progress
  const done = Number(progress?.done ?? phase.counts?.ok ?? 0)
  const total = Number(progress?.total ?? phase.counts?.items ?? 0)
  const pending = isTaskRunPending(phase.status)
  const cleaned = 'dataset_dir' in phase ? phase.cleanup_verified : phase.execution?.cleanup_verified === true
  const retry = ['failed', 'cancelled', 'interrupted'].includes(phase.status)
  return <section className="conv-body" aria-label={t('conv.phaseTitle')}>
    <div className="conv-row"><strong>{t('conv.phaseTitle')}</strong><RunStatusBadge status={phase.status} /></div>
    <p className="muted">{t('conv.phaseProgress', { done, total })}</p>
    {pending && total > 0 ? <Progress value={done} total={total} /> : null}
    {phase.error ? <p className="field-error">{phase.error}</p> : null}
    <p className="muted conv-help">{t('conv.phaseHelp')}</p>
    <div className="conv-row conv-actions">
      {retry ? <button type="button" className="btn" disabled={busy || !cleaned} onClick={() => onControl('resume')}>{t('conv.retryPhase')}</button> : null}
      {pending && phase.status !== 'cancelling' && phase.status !== 'cleanup_pending' && phase.status !== 'reconciling' ? <button type="button" className="btn" disabled={busy} onClick={() => onControl('cancel')}>{t('conv.cancelPhase')}</button> : null}
      {phase.status === 'cleanup_pending' ? <span role="status">{t('conv.phaseCleanup')}</span> : null}
    </div>
  </section>
}
