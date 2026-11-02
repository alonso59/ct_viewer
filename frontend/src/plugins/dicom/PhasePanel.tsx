import { useTranslation } from 'react-i18next'

import { isTaskRunPending, type SourceOperation } from '../../api'
import { Button, ConfirmInline, Progress, RunStatusBadge } from '../../lib'

export function PhasePanel({ phase, busy, conversionComplete, onControl }: { phase: NonNullable<SourceOperation['phase_run']>; busy: boolean; conversionComplete: boolean; onControl: (action: 'resume' | 'cancel') => void }) {
  const { t } = useTranslation()
  const progress = phase.progress
  const done = Number(progress?.done ?? phase.counts?.ok ?? 0)
  const total = Number(progress?.total ?? phase.counts?.items ?? 0)
  const pending = isTaskRunPending(phase.status)
  const cleaned = 'dataset_dir' in phase ? phase.cleanup_verified : phase.execution?.cleanup_verified === true
  const retry = ['failed', 'cancelled', 'interrupted'].includes(phase.status)
  return <section className="conv-body" aria-label={t('conv.phaseTitle')}>
    <div className="conv-row"><strong>{t('conv.phaseTitle')}</strong><RunStatusBadge status={phase.status} /></div>
    {total > 0 ? <p className="muted num">{t('conv.phaseProgress', { done, total })}</p> : null}
    {pending && total > 0 ? <Progress value={done} total={total} label={t('conv.phaseTitle')} /> : null}
    {phase.error ? <p className="field-error">{phase.error}</p> : null}
    <p className="muted conv-help">{t('conv.phaseHelp')}</p>
    <div className="conv-row conv-actions">
      {retry ? <Button className="btn" disabled={busy || !cleaned || !conversionComplete} reason={t(!conversionComplete ? 'reason.conversionFirst' : !cleaned ? 'reason.cleanup' : 'reason.working')} onClick={() => onControl('resume')}>{t('conv.retryPhase')}</Button> : null}
      {pending && phase.status !== 'cancelling' && phase.status !== 'cleanup_pending' && phase.status !== 'reconciling' ? <ConfirmInline question={t('conv.cancelPhaseConfirm')} confirm={t('common.yesCancel')} onConfirm={() => onControl('cancel')} trigger={(ask) => <button type="button" className="btn" disabled={busy} onClick={ask}>{t('conv.cancelPhase')}</button>} /> : null}
      {phase.status === 'cleanup_pending' ? <span role="status">{t('conv.phaseCleanup')}</span> : null}
    </div>
  </section>
}
