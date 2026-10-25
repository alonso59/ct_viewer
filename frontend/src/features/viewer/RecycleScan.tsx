// Preview and explicitly confirm recycling an entire scan and its related outputs.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, ReviewerCancelled, useRecycleScan, type ItemRecord } from '../../api'
import { Dialog, ProblemCard } from '../../lib'
import { registry } from '../../shell'
import { Icon, codicon } from '../../theme'

export function RecycleScan({ pid, item, onRecycled }: { pid: string; item: ItemRecord; onRecycled: () => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const plan = useQuery({ queryKey: keys.recycle(pid, item.item_id), queryFn: () => api.previewRecycle(pid, item.item_id), enabled: open, staleTime: 0 })
  const recycle = useRecycleScan(pid, item.item_id)
  if (registry.readOnly) return null
  const close = () => {
    if (!recycle.isPending) { setOpen(false); recycle.reset() }
  }
  const confirm = () => {
    if (!plan.data || plan.isFetching) return
    recycle.mutate(plan.data.token, { onSuccess: () => { setOpen(false); onRecycled() } })
  }
  return <>
    <button type="button" className="icon-btn recycle-scan-button" aria-label={t('recycle.button')} title={t('recycle.button')} onClick={() => setOpen(true)}>
      <Icon spec={codicon('trash')} />
    </button>
    {open ? <Dialog open onOpenChange={(o) => { if (!o) close() }} title={t('recycle.title', { case: item.case_id, scan: item.scan_idx })} icon={codicon('trash')} footer={<>
      <button type="button" className="btn" disabled={recycle.isPending} onClick={close}>{t('common.cancel')}</button>
      <button type="button" className="btn danger" disabled={!plan.data || plan.isFetching || plan.isError || recycle.isPending} onClick={confirm}>{t(recycle.isPending ? 'recycle.moving' : 'recycle.button')}</button>
    </>}>
      <p>{t('recycle.help')}</p>
      {plan.isPending ? <p>{t('common.loading')}</p> : null}
      {plan.isError ? <ProblemCard error={plan.error} /> : null}
      {plan.data ? <>
        <p>{t('recycle.counts', { items: plan.data.item_ids.length, files: plan.data.n_files, rows: plan.data.n_metadata_rows })}</p>
        <p className="mono" style={{ overflowWrap: 'anywhere' }}>{plan.data.recycle_bin}</p>
        {plan.data.projects.length > 1 ? <p>{t('recycle.shared', { count: plan.data.projects.length })}</p> : null}
      </> : null}
      {recycle.error && !(recycle.error instanceof ReviewerCancelled) ? <ProblemCard error={recycle.error} /> : null}
    </Dialog> : null}
  </>
}
