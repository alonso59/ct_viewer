// The discovery and conversion progress pieces the converter window and the batch board share.
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'

import { isTaskRunPending, type ConversionTimeEstimate, type SourceOperation } from '../../api'
import { fmtBytes, fmtEtaRange, fmtInt, IndeterminateProgress, Progress } from '../../lib'

type RunProgress = Record<string, number | string | null | undefined> | null | undefined

/** What a stage is doing and how far it is; `total` 0 means the stage has no known end yet */
export interface StageCount {
  stage: string
  done: number
  total: number
}

/** The batch-status key for an operation's own work before its conversion runs: discovery, dry run or source check */
export function preparingKey(op: SourceOperation): 'discovering' | 'planning' | 'verifying' | null {
  if (!isTaskRunPending(op.status) || op.conversion_run || op.stage === 'converting') return null
  return op.work_kind === 'estimate' ? 'planning' : op.work_kind === 'convert' ? 'verifying' : 'discovering'
}

/** The counter of a source operation's current stage: files while it scans, headers or series while it analyses */
export function operationCount(op: SourceOperation): StageCount {
  const p = op.progress ?? {}
  const stage = op.progress_stage
  if (stage === 'counting') return { stage, done: p.files_total ?? 0, total: 0 }
  // Only an analysis lists folders; a scan reports files against its pre-count.
  if (stage === 'listing' && op.work_kind === 'estimate') return { stage, done: p.done ?? 0, total: 0 }
  if (stage && stage !== 'admitted' && (p.total ?? 0) > 0) return { stage, done: p.done ?? 0, total: p.total ?? 0 }
  const own = op.work_kind === 'convert' ? 'verifying' : op.work_kind === 'estimate' ? 'check' : 'scanning'
  return { stage: own, done: p.files ?? 0, total: p.files_total ?? 0 }
}

/** A conversion run's counter: selected series once it converts, each earlier or later stage's own work otherwise */
export function runCount(p: RunProgress): StageCount {
  const stage = String(p?.stage ?? 'admitted')
  const total = Number(p?.total ?? 0)
  if ((stage === 'converting' || !p?.stage) && total > 0) return { stage: 'converting', done: Number(p?.done ?? 0), total }
  return { stage, done: Number(p?.stage_done ?? 0), total: Number(p?.stage_total ?? 0) }
}

/** "Reading headers · 1,200 / 4,500", "Listing folders · 340 so far" or just the stage name */
export function countLabel(t: TFunction, { stage, done, total }: StageCount): string {
  const name = t(`conv.stageName.${stage}`, { defaultValue: t(`conv.status.${stage}`, { defaultValue: stage }) })
  if (total > 0) return t('conv.countOf', { name, done: fmtInt(done), total: fmtInt(total) })
  return done > 0 ? t('conv.countSoFar', { name, done: fmtInt(done) }) : name
}

/** A stage's bar and label; the bar is indeterminate until the stage knows its end */
export function CountProgress({ count }: { count: StageCount }) {
  const { t } = useTranslation()
  return <>
    {count.total > 0 ? <Progress value={count.done} total={count.total} /> : <IndeterminateProgress />}
    <p className="muted conv-help num">{countLabel(t, count)}</p>
  </>
}

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

/** Discovery against the pre-counted total, with the time left and the size warning */
export function DiscoveryProgress({ operation }: { operation: SourceOperation }) {
  return <>
    <CountProgress count={operationCount(operation)} />
    <DiscoveryNotes operation={operation} />
  </>
}

/** The scan's time left and the inventory size warning, under whichever bar shows the scan */
export function DiscoveryNotes({ operation }: { operation: SourceOperation }) {
  const { t } = useTranslation()
  const eta = operation.discovery_eta as { low_s?: number | null; high_s?: number | null; basis?: string } | null | undefined
  const projection = operation.summary?.inventory_projection as { projected_bytes: number; cap_bytes: number; warning?: boolean } | null | undefined
  return <>
    {eta?.basis !== 'unknown' && eta?.low_s != null && eta.high_s != null ? <p className="muted conv-help">{fmtEtaRange(eta.low_s, eta.high_s)}</p> : null}
    {projection?.warning ? <p className="muted conv-help" role="note">{t('conv.projectionWarning', { projected: fmtBytes(projection.projected_bytes), cap: fmtBytes(projection.cap_bytes) })}</p> : null}
  </>
}
