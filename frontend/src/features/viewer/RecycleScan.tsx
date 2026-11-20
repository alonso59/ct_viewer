import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, ReviewerCancelled, useRecycleScan, type ItemRecord } from '../../api'
import { Dialog, ProblemCard } from '../../lib'
import { registry } from '../../shell'
import { Icon, codicon } from '../../theme'

export function RecycleScan({ pid, item, onRecycled }: { pid: string; item: ItemRecord; onRecycled: (itemIds: string[]) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const canRecycleVoi = item.scope === 'voi'
  const [wholeScan, setWholeScan] = useState(false)
  const scope = canRecycleVoi && !wholeScan ? 'voi' : 'scan'
  const buttonLabel = t(scope === 'voi' ? 'recycle.voiButton' : 'recycle.button')
  const voiName = item.side === '-' ? t('item.voi') : t('item.voiSide', { side: item.side })
  const plan = useQuery({ queryKey: keys.recycle(pid, item.item_id, scope), queryFn: () => api.previewRecycle(pid, item.item_id, scope), enabled: open, staleTime: 0 })
  const recycle = useRecycleScan(pid, item.item_id, scope)
  if (registry.readOnly) return null
  const close = () => {
    if (!recycle.isPending) { setOpen(false); recycle.reset() }
  }
  const confirm = () => {
    if (!plan.data || plan.isFetching) return
    recycle.mutate(plan.data.token, { onSuccess: (result) => { setOpen(false); onRecycled(result.item_ids) } })
  }
  return <>
    <button type="button" className="icon-btn recycle-scan-button" aria-label={t(canRecycleVoi ? 'recycle.voiButton' : 'recycle.button')} title={t(canRecycleVoi ? 'recycle.voiButton' : 'recycle.button')} onClick={() => { setWholeScan(false); setOpen(true) }}>
      <Icon spec={codicon('trash')} />
    </button>
    {open ? <Dialog open onOpenChange={(o) => { if (!o) close() }} title={t(scope === 'voi' ? 'recycle.voiTitle' : 'recycle.title', { case: item.case_id, scan: item.scan_idx, voi: voiName })} icon={codicon('trash')} footer={<>
      <button type="button" className="btn" disabled={recycle.isPending} onClick={close}>{t('common.cancel')}</button>
      <button type="button" className="btn btn-danger" disabled={!plan.data || plan.isFetching || plan.isError || recycle.isPending} onClick={confirm}>{recycle.isPending ? t('recycle.moving') : buttonLabel}</button>
    </>}>
      {canRecycleVoi ? (
        <div className="seg" role="group" aria-label={t('recycle.scope')}>
          <button type="button" aria-pressed={scope === 'voi'} disabled={recycle.isPending} onClick={() => { setWholeScan(false); recycle.reset() }}>{voiName}</button>
          <button type="button" aria-pressed={scope === 'scan'} disabled={recycle.isPending} onClick={() => { setWholeScan(true); recycle.reset() }}>{t('recycle.wholeScan')}</button>
        </div>
      ) : null}
      <p>{t(scope === 'voi' ? 'recycle.voiHelp' : 'recycle.help')}</p>
      {plan.isPending ? <p>{t('common.loading')}</p> : null}
      {plan.isError ? <ProblemCard error={plan.error} onRetry={() => void plan.refetch()} /> : null}
      {plan.data ? <>
        <p>{t('recycle.counts', { items: plan.data.item_ids.length, files: plan.data.n_files, rows: plan.data.n_metadata_rows })}</p>
        <p className="mono" style={{ overflowWrap: 'anywhere' }}>{plan.data.recycle_bin}</p>
        {plan.data.projects.length > 1 ? <p>{t('recycle.shared', { count: plan.data.projects.length })}</p> : null}
      </> : null}
      {recycle.error && !(recycle.error instanceof ReviewerCancelled) ? <ProblemCard error={recycle.error} /> : null}
    </Dialog> : null}
  </>
}
