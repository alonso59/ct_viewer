// The discovery and conversion progress pieces the converter window and the batch board share.
import { useTranslation } from 'react-i18next'

import type { ConversionTimeEstimate, SourceOperation } from '../../api'
import { fmtBytes, fmtEtaRange, IndeterminateProgress, Progress } from '../../lib'

type RunProgress = Record<string, number | string | null | undefined> | null | undefined

/** Bytes converted against planned and the measured speed; shown while the time estimate is still unknown */
export function ConversionBytes({ progress }: { progress: RunProgress }) {
  const { t } = useTranslation()
  const done = Number(progress?.bytes_done ?? 0)
  const total = Number(progress?.bytes_total ?? 0)
  const rate = Number(progress?.bytes_per_s ?? 0)
  if (!(total > 0)) return null
  return <>
    <p className="muted conv-help num">{t('conv.bytesProgress', { done: fmtBytes(done), total: fmtBytes(total), percent: Math.min(100, Math.floor((done / total) * 100)) })}</p>
    {rate > 0 ? <p className="muted conv-help num">{t('conv.bytesRate', { rate: fmtBytes(rate) })}</p> : null}
  </>
}

export function ConversionTime({ value, progress }: { value: ConversionTimeEstimate | null | undefined; progress?: RunProgress }) {
  const { t } = useTranslation()
  if (value?.basis === 'history' && value.lower_s != null && value.upper_s != null) {
    return <>
      <p className="muted conv-help">{t('conv.etaHistoryRange', { range: fmtEtaRange(value.lower_s, value.upper_s), n: value.sample_count })}</p>
      <p className="muted conv-help">{t('conv.etaStages')}</p>
    </>
  }
  return <>
    <p className="muted conv-help">{t(value?.basis === 'complete' ? 'conv.etaComplete' : 'conv.etaUnknown')}</p>
    {value?.basis === 'complete' ? null : <ConversionBytes progress={progress} />}
  </>
}

/** Discovery against the pre-counted total, with the time left and the size warning; nothing before a total exists */
export function DiscoveryProgress({ operation }: { operation: SourceOperation }) {
  const { t } = useTranslation()
  const files = operation.progress?.files ?? 0
  const total = operation.progress?.files_total ?? 0
  const eta = operation.discovery_eta as { low_s?: number | null; high_s?: number | null; basis?: string } | null | undefined
  const projection = operation.summary?.inventory_projection as { projected_bytes: number; cap_bytes: number; warning?: boolean } | null | undefined
  const counting = operation.progress_stage === 'counting'
  return <>
    {counting ? <>
      <IndeterminateProgress />
      <p className="muted conv-help">{t('conv.counting')}</p>
    </> : total > 0 ? <>
      <Progress value={files} total={total} />
      <p className="muted conv-help num">{t('conv.discoveryProgress', { done: files, total, percent: Math.min(100, Math.round((files / total) * 100)) })}</p>
      {eta?.basis !== 'unknown' && eta?.low_s != null && eta.high_s != null ? <p className="muted conv-help">{fmtEtaRange(eta.low_s, eta.high_s)}</p> : null}
    </> : null}
    {projection?.warning ? <p className="muted conv-help" role="note">{t('conv.projectionWarning', { projected: fmtBytes(projection.projected_bytes), cap: fmtBytes(projection.cap_bytes) })}</p> : null}
  </>
}
