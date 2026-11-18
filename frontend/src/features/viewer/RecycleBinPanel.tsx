// The project's recycled scans: restore one, or delete it for good after typing its case ID.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, ReviewerCancelled, useDeleteRecycled, useRecycleBin, useRestoreScan, type RecycleBinEntry } from '../../api'
import { Dialog, fmtDate, ProblemCard } from '../../lib'
import { toast, useWorkbench } from '../../shell'
import { codicon } from '../../theme'

const scanName = (e: RecycleBinEntry) => (e.case_id ? `${e.case_id} · ${e.scan_idx ?? ''}` : e.item_ids.join(', '))

function RestoreDialog({ pid, entry, onClose }: { pid: string; entry: RecycleBinEntry; onClose: () => void }) {
  const { t } = useTranslation()
  const plan = useQuery({ queryKey: keys.restore(pid, entry.recycle_id), queryFn: () => api.previewRestore(pid, entry.recycle_id), staleTime: 0, retry: false })
  const restore = useRestoreScan(pid)
  const close = () => { if (!restore.isPending) onClose() }
  const confirm = () => {
    if (!plan.data || plan.isFetching) return
    restore.mutate({ rid: entry.recycle_id, token: plan.data.token }, {
      onSuccess: () => { toast({ message: t('recycleBin.restored', { scan: scanName(entry) }), tone: 'ok' }); onClose() },
    })
  }
  return <Dialog open onOpenChange={(o) => { if (!o) close() }} title={t('recycleBin.restoreTitle', { scan: scanName(entry) })} icon={codicon('discard')} footer={<>
    <button type="button" className="btn" disabled={restore.isPending} onClick={close}>{t('common.cancel')}</button>
    <button type="button" className="btn btn-primary" disabled={!plan.data || plan.isFetching || plan.isError || restore.isPending} onClick={confirm}>{t(restore.isPending ? 'recycleBin.restoring' : 'recycleBin.restore')}</button>
  </>}>
    <p>{t('recycleBin.restoreHelp')}</p>
    {plan.isPending ? <p>{t('common.loading')}</p> : null}
    {plan.isError ? <ProblemCard error={plan.error} onRetry={() => void plan.refetch()} /> : null}
    {plan.data ? <>
      <p>{t('recycleBin.restoreCounts', { items: plan.data.item_ids.length, files: plan.data.n_files, tables: plan.data.n_metadata_files })}</p>
      {plan.data.projects.length > 1 ? <p>{t('recycle.shared', { count: plan.data.projects.length })}</p> : null}
    </> : null}
    {restore.error && !(restore.error instanceof ReviewerCancelled) ? <ProblemCard error={restore.error} /> : null}
  </Dialog>
}

function DeleteDialog({ pid, entry, onClose }: { pid: string; entry: RecycleBinEntry; onClose: () => void }) {
  const { t } = useTranslation()
  const remove = useDeleteRecycled(pid)
  const [typed, setTyped] = useState('')
  const expected = entry.case_id ?? entry.recycle_id
  const close = () => { if (!remove.isPending) onClose() }
  const confirm = () => remove.mutate(entry.recycle_id, {
    onSuccess: () => { toast({ message: t('recycleBin.deleted', { scan: scanName(entry) }), tone: 'ok' }); onClose() },
  })
  return <Dialog open onOpenChange={(o) => { if (!o) close() }} title={t('recycleBin.deleteTitle', { scan: scanName(entry) })} icon={codicon('trash')} footer={<>
    <button type="button" className="btn" disabled={remove.isPending} onClick={close}>{t('common.cancel')}</button>
    <button type="button" className="btn btn-danger" disabled={typed.trim() !== expected || remove.isPending} onClick={confirm}>{t(remove.isPending ? 'recycleBin.deleting' : 'recycleBin.delete')}</button>
  </>}>
    <p>{t('recycleBin.deleteHelp', { files: entry.n_files })}</p>
    <label className="field">
      <span className="field-label">{t('recycleBin.typeToConfirm', { id: expected })}</span>
      <input className="input mono" value={typed} autoComplete="off" spellCheck={false} onChange={(e) => setTyped(e.target.value)} />
    </label>
    {remove.error ? <ProblemCard error={remove.error} /> : null}
  </Dialog>
}

export default function RecycleBinPanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((state) => state.pid) ?? ''
  const bin = useRecycleBin(pid)
  const [action, setAction] = useState<{ kind: 'restore' | 'delete'; entry: RecycleBinEntry } | null>(null)
  if (bin.error) return <ProblemCard error={bin.error} onRetry={() => void bin.refetch()} />
  const rows = bin.data ?? []
  return (
    <div className="segmentation-panel">
      <h2>{t('recycleBin.title')}</h2>
      <p className="muted">{t('recycleBin.help')}</p>
      <div className="segmentation-labels">
        <table className="segmentation-table">
          <thead><tr>
            <th>{t('recycleBin.scan')}</th><th>{t('recycleBin.at')}</th><th>{t('recycleBin.reviewer')}</th><th className="num">{t('recycleBin.files')}</th>
            <th>{t('psettings.actions')}</th>
          </tr></thead>
          <tbody>{rows.map((entry) => (
            <tr key={entry.recycle_id}>
              <td className="mono">{scanName(entry)}{entry.projects.length > 1 ? <span className="muted">{t('recycleBin.projects', { count: entry.projects.length })}</span> : null}</td>
              <td>{entry.at ? fmtDate(entry.at) : '—'}</td>
              <td>{entry.reviewer || '—'}</td>
              <td className="num">{entry.available ? entry.n_files : <span className="muted" title={t('recycleBin.missingHelp')}>{t('recycleBin.missing')}</span>}</td>
              <td>
                <button type="button" className="btn btn-sm" disabled={!entry.available} aria-label={t('recycleBin.restoreLabel', { scan: scanName(entry) })} onClick={() => setAction({ kind: 'restore', entry })}>{t('recycleBin.restore')}</button>{' '}
                <button type="button" className="btn btn-sm btn-danger" aria-label={t('recycleBin.deleteLabel', { scan: scanName(entry) })} onClick={() => setAction({ kind: 'delete', entry })}>{t('recycleBin.delete')}</button>
              </td>
            </tr>
          ))}</tbody>
        </table>
        {bin.isPending ? <p>{t('common.loading')}</p> : !rows.length ? <p className="muted">{t('recycleBin.empty')}</p> : null}
      </div>
      {action?.kind === 'restore' ? <RestoreDialog pid={pid} entry={action.entry} onClose={() => setAction(null)} /> : null}
      {action?.kind === 'delete' ? <DeleteDialog pid={pid} entry={action.entry} onClose={() => setAction(null)} /> : null}
    </div>
  )
}
