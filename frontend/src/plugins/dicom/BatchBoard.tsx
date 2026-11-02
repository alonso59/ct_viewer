// One row per batch of a plan, with the plan's controls. Each batch converts into its own dataset;
// a project is only created when the user asks for it on a finished batch.
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, isTaskRunPending, keys, ProblemError, useBatchPlan, useBatchPlanCommand, useBatchPlans, useSourceOperation, type SourceBatch, type SourceBatchPlan, type SourceOperation } from '../../api'
import { NewProjectDialog } from '../../features/import'
import { fmtEtaRange, IndeterminateProgress, ProblemCard } from '../../lib'
import { filesCell } from './BatchPreview'
import { showOperationOutput } from './output'
import { useConverter } from './store'
import { ConversionBytes, CountProgress, DiscoveryProgress, preparingKey, runCount } from './OperationProgress'

type Command = Parameters<ReturnType<typeof useBatchPlanCommand>['mutate']>[0]

/** The same fence the converter window sends to resume or retry an operation */
const fence = (op: SourceOperation) => ({ expected_revision: op.revision, expected_attempt: op.attempt, ...(op.conversion_run ? { expected_run_attempt: op.conversion_run.attempts } : {}) })

function ConvertingProgress({ operation }: { operation: SourceOperation }) {
  const run = operation.conversion_run
  const progress = run?.progress as Record<string, number | string | null | undefined> | undefined
  const eta = run?.conversion_time
  return <>
    <CountProgress count={runCount(progress)} />
    {eta?.basis === 'history' && eta.lower_s != null && eta.upper_s != null ? <p className="muted conv-help">{fmtEtaRange(eta.lower_s, eta.upper_s)}</p> : <ConversionBytes progress={progress} />}
  </>
}

function BatchRow({ plan, batch, busy, onCreate, onError, onResumed, onOpenOperation }: {
  plan: SourceBatchPlan; batch: SourceBatch; busy: boolean
  onCreate: (b: SourceBatch) => void; onError: (e: unknown) => void; onResumed: () => void; onOpenOperation: (id: string) => void
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
    <tr data-testid={`batch-${batch.index}`} data-status={batch.status} data-current={plan.batches[plan.cursor]?.index === batch.index && plan.status !== 'completed' ? true : undefined}>
      <td>
        <strong>{batch.name}</strong>
        {dataset && dataset !== batch.name ? <div className="muted conv-help">{dataset}</div> : null}
      </td>
      <td className="num">{batch.folder_count}</td>
      <td className="num">{filesCell(plan, batch.files_total, t('conv.counting'))}</td>
      <td><span className="badge" data-status={batch.status}>{t(`conv.batches.status.${preparing ?? (working && batch.status === 'attention' ? 'converting' : batch.status)}`)}</span></td>
      <td className="conv-batch-detail">
        {working && operation ? (converting ? <ConvertingProgress operation={operation} /> : <DiscoveryProgress operation={operation} />) : null}
        <div className="conv-row">
          {batch.operation_id ? <button type="button" className="btn btn-sm" onClick={() => onOpenOperation(batch.operation_id!)}>{t('conv.batches.details')}</button> : null}
          {operation ? <button type="button" className="btn btn-sm" onClick={() => { useConverter.getState().minimize(); showOperationOutput(operation) }}>{t('conv.showOutput')}</button> : null}
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

/** A stopped batch's problem under the table: what happened in one line, the full report on request */
function BatchProblem({ batch }: { batch: SourceBatch }) {
  const { t } = useTranslation()
  const operation = useSourceOperation(batch.operation_id).data
  if (!batch.error || (operation && isTaskRunPending(operation.status))) return null
  // A worker report ends with the exception that stopped it; that line says what happened.
  const lines = batch.error.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  const summary = lines.at(-1) ?? batch.error
  return (
    <li className="error-card" role="alert">
      {t('conv.batches.problem', { batch: batch.name, problem: summary })}
      {lines.length > 1 ? <details><summary>{t('conv.batches.problemDetails')}</summary><pre className="mono">{batch.error}</pre></details> : null}
    </li>
  )
}

/** Every batch plan that is not cancelled, so its board can be reopened from the converter */
export function BatchPlanList({ current, onOpen }: { current: string | null; onOpen: (planId: string) => void }) {
  const { t } = useTranslation()
  // A plan never started is a preview the user did not review; only the open one is listed.
  const plans = (useBatchPlans().data ?? []).filter((p) => p.status !== 'cancelled' && (p.status !== 'pending' || p.plan_id === current))
  if (!plans.length) return null
  return (
    <details className="conv-plans" data-testid="batch-plans">
      <summary>{t('conv.batches.plans', { n: plans.length })}</summary>
      <ul>
        {plans.map((p) => (
          <li key={p.plan_id} className="conv-row">
            <strong>{p.name}</strong>
            <span className="badge" data-status={p.status}>{t(`conv.batches.plan.${p.status}`)}</span>
            <span className="muted conv-help num">{t('conv.batches.done', { done: p.batches.filter((b) => b.status === 'completed').length, total: p.batches.length })}</span>
            <span style={{ flex: 1 }} />
            <button type="button" className="btn btn-sm" disabled={p.plan_id === current} onClick={() => onOpen(p.plan_id)}>{t('conv.batches.open')}</button>
          </li>
        ))}
      </ul>
    </details>
  )
}

export function BatchBoard({ planId, onNew, onProjectClosed, onOpenOperation }: { planId: string; onNew: () => void; onProjectClosed: () => void; onOpenOperation: (id: string) => void }) {
  const { t } = useTranslation()
  const query = useBatchPlan(planId)
  const plan = query.data
  const command = useBatchPlanCommand(planId)
  const [error, setError] = useState<unknown>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [creating, setCreating] = useState<SourceBatch | null>(null)
  const [confirming, setConfirming] = useState(false)
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
        <IndeterminateProgress label={t('conv.counting')} />
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
              <BatchRow key={b.index} plan={plan} batch={b} busy={busy} onCreate={setCreating} onError={setError} onResumed={() => void query.refetch()} onOpenOperation={onOpenOperation} />
            ))}
          </tbody>
        </table>
      </div>
      {plan.batches.some((b) => b.status === 'attention' && b.error) ? <ul className="conv-problems" aria-label={t('conv.batches.problems')}>
        {plan.batches.filter((b) => b.status === 'attention').map((b) => <BatchProblem key={b.index} batch={b} />)}
      </ul> : null}
      <div className="conv-row conv-actions">
        {plan.status === 'pending' ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run('start')}>{t('conv.batches.start')}</button> : null}
        {plan.status === 'running' && current?.status === 'ready' ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run('continue')}>{t('conv.batches.convertThis')}</button> : null}
        {plan.status === 'paused' ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run('continue')}>{t('conv.batches.continue')}</button> : null}
        {live ? <button type="button" className="btn" aria-pressed={plan.auto} disabled={busy} onClick={() => void run({ auto: !plan.auto })}>{t(plan.auto ? 'conv.batches.stopAuto' : 'conv.batches.auto')}</button> : null}
        {live ? <button type="button" className="btn" disabled={busy} onClick={() => void run('add-new-folders')}>{t('conv.batches.addFolders')}</button> : null}
        {live && !confirming ? <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(true)}>{t('conv.batches.cancel')}</button> : null}
        {live && confirming ? <>
          <span role="note">{t('conv.batches.cancelConfirm')}</span>
          <button type="button" className="btn btn-danger" disabled={busy} onClick={() => { setConfirming(false); void run('cancel') }}>{t('conv.batches.cancelYes')}</button>
          <button type="button" className="btn" onClick={() => setConfirming(false)}>{t('conv.batches.keep')}</button>
        </> : null}
        {!live ? <button type="button" className="btn" onClick={onNew}>{t('conv.newOperation')}</button> : null}
      </div>
      {message ? <p className="muted conv-help" role="status">{message}</p> : null}
      {error ? <ProblemCard error={error} /> : null}
      {creating?.dataset ? <NewProjectDialog open onOpenChange={(o) => { if (!o) { setCreating(null); onProjectClosed() } }} prefill={{ path: creating.dataset }} name={creating.name} /> : null}
    </div>
  )
}
