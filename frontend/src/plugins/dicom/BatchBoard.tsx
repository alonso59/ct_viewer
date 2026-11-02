// One row per batch of a plan, with the plan's controls. Each batch converts into its own dataset;
// a project is only created when the user asks for it on a finished batch.
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, isTaskRunPending, keys, ProblemError, useBatchPlan, useBatchPlanCommand, useSourceOperation, type SourceBatch, type SourceBatchPlan, type SourceOperation } from '../../api'
import { NewProjectDialog } from '../../features/import'
import { fmtEtaRange, IndeterminateProgress, ProblemCard, Progress } from '../../lib'
import { filesCell } from './BatchPreview'
import { ConversionBytes, DiscoveryProgress, PlanningProgress, preparingKey } from './OperationProgress'

type Command = Parameters<ReturnType<typeof useBatchPlanCommand>['mutate']>[0]

/** The same fence the converter window sends to resume or retry an operation */
const fence = (op: SourceOperation) => ({ expected_revision: op.revision, expected_attempt: op.attempt, ...(op.conversion_run ? { expected_run_attempt: op.conversion_run.attempts } : {}) })

function ConvertingProgress({ operation }: { operation: SourceOperation }) {
  const { t } = useTranslation()
  const run = operation.conversion_run
  const progress = run?.progress as Record<string, number | string | null | undefined> | undefined
  const done = Number(progress?.done ?? 0)
  const total = Number(progress?.total ?? 0)
  const eta = run?.conversion_time
  return <>
    {total > 0 ? <Progress value={done} total={total} /> : <IndeterminateProgress />}
    {total > 0 ? <p className="muted conv-help num">{t('conv.converting', { done, total })}</p> : null}
    {eta?.basis === 'history' && eta.lower_s != null && eta.upper_s != null ? <p className="muted conv-help">{fmtEtaRange(eta.lower_s, eta.upper_s)}</p> : <ConversionBytes progress={progress} />}
  </>
}

function BatchRow({ plan, batch, busy, onCreate, onError, onResumed }: {
  plan: SourceBatchPlan; batch: SourceBatch; busy: boolean
  onCreate: (b: SourceBatch) => void; onError: (e: unknown) => void; onResumed: () => void
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const operation = useSourceOperation(batch.status === 'pending' ? null : batch.operation_id).data
  const control = useMutation({
    mutationFn: ({ op, action }: { op: SourceOperation; action: 'resume' | 'retry_failed' }) =>
      action === 'resume' ? api.resumeSourceOperation(op.operation_id, fence(op)) : api.retryFailedSourceOperation(op.operation_id, fence(op)),
    onSuccess: (op) => {
      qc.setQueryData(keys.sourceOperation(op.operation_id), op)
      onResumed()
    },
    onError,
  })
  const working = !!operation && isTaskRunPending(operation.status)
  const preparing = operation ? preparingKey(operation) : null
  const converting = !preparing && (batch.status === 'converting' || !!operation?.conversion_run)
  const failed = operation?.conversion_run?.counts?.failed ?? 0
  const fixable = !!operation && !working && operation.cleanup_verified
  const dataset = batch.dataset?.split('/').at(-1)
  return (
    <tr data-testid={`batch-${batch.index}`} data-status={batch.status}>
      <td>
        <strong>{batch.name}</strong>
        {dataset && dataset !== batch.name ? <div className="muted conv-help">{dataset}</div> : null}
      </td>
      <td className="num">{batch.folder_count}</td>
      <td className="num">{filesCell(plan, batch.files_total, t('conv.counting'))}</td>
      <td><span className="badge" data-status={batch.status}>{t(`conv.batches.status.${preparing ?? batch.status}`)}</span></td>
      <td className="conv-batch-detail">
        {working && operation ? (converting ? <ConvertingProgress operation={operation} /> : preparing === 'planning' ? <PlanningProgress operation={operation} /> : <DiscoveryProgress operation={operation} />) : null}
        {batch.status === 'attention' && batch.error ? <p className="error-card" role="alert">{batch.error}</p> : null}
        <div className="conv-row">
          {batch.status === 'completed' && batch.dataset ? <button type="button" className="btn btn-sm" onClick={() => onCreate(batch)}>{t('conv.batches.createProject')}</button> : null}
          {batch.status === 'attention' && operation ? <>
            <button type="button" className="btn btn-sm btn-primary" disabled={busy || control.isPending || !fixable} onClick={() => control.mutate({ op: operation, action: 'resume' })}>{t('conv.resumePending')}</button>
            {failed > 0 ? <button type="button" className="btn btn-sm" disabled={busy || control.isPending || !fixable} onClick={() => control.mutate({ op: operation, action: 'retry_failed' })}>{t('conv.retryFailed')}</button> : null}
          </> : null}
        </div>
      </td>
    </tr>
  )
}

export function BatchBoard({ planId, onNew, onProjectClosed }: { planId: string; onNew: () => void; onProjectClosed: () => void }) {
  const { t } = useTranslation()
  const query = useBatchPlan(planId)
  const plan = query.data
  const command = useBatchPlanCommand(planId)
  const [error, setError] = useState<unknown>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [creating, setCreating] = useState<SourceBatch | null>(null)
  const run = async (cmd: Command) => {
    setError(null)
    setMessage(null)
    try {
      await command.mutateAsync(cmd)
    } catch (e) {
      if (cmd === 'add-new-folders' && e instanceof ProblemError && e.status === 409) setMessage(t('conv.batches.noNewFolders'))
      else setError(e)
    }
  }
  if (!plan) return query.error ? <ProblemCard error={query.error} /> : <p role="status">{t('common.loading')}</p>
  const current = plan.batches[plan.cursor]
  const live = plan.status === 'pending' || plan.status === 'running' || plan.status === 'paused'
  const done = plan.batches.filter((b) => b.status === 'completed').length
  const busy = command.isPending
  return (
    <div className="conv-body" data-testid="batch-board">
      <div className="conv-row">
        <strong>{plan.name}</strong>
        <span className="badge" data-status={plan.status}>{t(`conv.batches.plan.${plan.status}`)}</span>
        <span className="muted conv-help num">{t('conv.batches.done', { done, total: plan.batches.length })}</span>
      </div>
      {live && plan.eta.basis === 'completed_batches' && plan.eta.low_s != null && plan.eta.high_s != null
        ? <p className="muted conv-help" data-testid="batch-overall-eta">{t('conv.batches.overallEta', { range: fmtEtaRange(plan.eta.low_s, plan.eta.high_s) })}</p> : null}
      {plan.counting === 'counting' ? <>
        <IndeterminateProgress />
        <p className="muted conv-help">{t('conv.counting')}</p>
      </> : null}
      {plan.warnings.length ? <ul className="conv-warnings" aria-label={t('conv.batches.warnings')}>
        {plan.warnings.map((w) => <li key={w.batch_index} role="note">{t('conv.batches.duplicatePatients', { batch: plan.batches[w.batch_index]?.name ?? w.batch_index + 1, count: w.patients })}</li>)}
      </ul> : null}
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>{t('conv.batches.batch')}</th>
              <th className="num">{t('conv.batches.patients')}</th>
              <th className="num">{t('conv.batches.files')}</th>
              <th>{t('conv.batches.state')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {plan.batches.map((b) => (
              <BatchRow key={b.index} plan={plan} batch={b} busy={busy} onCreate={setCreating} onError={setError} onResumed={() => void query.refetch()} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="conv-row conv-actions">
        {plan.status === 'pending' ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run('start')}>{t('conv.batches.start')}</button> : null}
        {plan.status === 'running' && current?.status === 'ready' ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run('continue')}>{t('conv.batches.convertThis')}</button> : null}
        {plan.status === 'paused' ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run('continue')}>{t('conv.batches.continue')}</button> : null}
        {live ? <button type="button" className="btn" aria-pressed={plan.auto} disabled={busy} onClick={() => void run({ auto: !plan.auto })}>{t(plan.auto ? 'conv.batches.stopAuto' : 'conv.batches.auto')}</button> : null}
        {live ? <button type="button" className="btn" disabled={busy} onClick={() => void run('cancel')}>{t('conv.batches.cancel')}</button> : null}
        {plan.status !== 'cancelled' ? <button type="button" className="btn" disabled={busy} onClick={() => void run('add-new-folders')}>{t('conv.batches.addFolders')}</button> : null}
        {!live ? <button type="button" className="btn" onClick={onNew}>{t('conv.newOperation')}</button> : null}
      </div>
      {message ? <p className="muted conv-help" role="status">{message}</p> : null}
      {error ? <ProblemCard error={error} /> : null}
      {creating?.dataset ? <NewProjectDialog open onOpenChange={(o) => { if (!o) { setCreating(null); onProjectClosed() } }} prefill={{ path: creating.dataset }} name={creating.name} /> : null}
    </div>
  )
}
