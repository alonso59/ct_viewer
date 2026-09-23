// Correction queue editor tab (CUR-09): items in the queue set or flagged; CSV export for 3D Slicer
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { QUEUE_STATUSES, useQueue, type CurationStatus } from '../../api'
import { PhaseChip, StatusBadge, fmtAgo } from '../../lib'
import { toast, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { openItem } from '../explorer'

const COLS = ['case_id', 'item_id', 'scope', 'side', 'phase', 'target', 'status', 'priority', 'comment', 'reviewer', 'at', 'image_path_abs', 'mask_path_abs'] as const

export function QueueEditor() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, isLoading } = useQueue(pid)
  const [status, setStatus] = useState<CurationStatus | ''>('')
  const rows = (data ?? []).filter((r) => !status || r.status === status)

  const exportCsv = () => {
    const esc = (v: unknown) => `"${String(v ?? '').replaceAll('"', '""')}"`
    const lines = [COLS.join(',')].concat(
      rows.map((r) =>
        [r.case_id, r.item_id, r.item?.scope, r.item?.side, r.item?.phase.canonical, r.target, r.status, r.priority, r.comment, r.reviewer, r.at, r.image_abs, r.mask_abs]
          .map(esc)
          .join(','),
      ),
    )
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }))
    a.download = 'correction_queue.csv'
    a.click()
    URL.revokeObjectURL(a.href)
    toast({ message: t('queue.exported', { count: rows.length }), tone: 'ok' })
  }

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <Icon spec={codicon('checklist')} />
        <strong>{t('queue.title')}</strong>
        <span className="count">{rows.length}</span>
        <span className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('queue.subtitle')}</span>
        <span style={{ flex: 1 }} />
        <select className="select input-sm" value={status} onChange={(e) => setStatus(e.target.value as CurationStatus | '')} aria-label={t('search.status')}>
          <option value="">{t('queue.allStatuses')}</option>
          {QUEUE_STATUSES.map((s) => (
            <option key={s} value={s}>{t(`status.${s}`)}</option>
          ))}
        </select>
        <button type="button" className="btn btn-sm" disabled={!rows.length} onClick={exportCsv}>
          <Icon spec={codicon('export')} />
          {t('queue.exportCsv')}
        </button>
      </div>
      {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
      {!isLoading && rows.length === 0 ? <div className="empty">{t('queue.empty')}</div> : null}
      {rows.length ? (
        <table className="table">
          <thead>
            <tr>
              <th>{t('queue.col.case')}</th>
              <th>{t('queue.col.item')}</th>
              <th>{t('queue.col.phase')}</th>
              <th>{t('queue.col.target')}</th>
              <th>{t('queue.col.status')}</th>
              <th>{t('queue.col.priority')}</th>
              <th>{t('queue.col.comment')}</th>
              <th>{t('queue.col.reviewer')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.item_id ?? r.case_id}|${r.target}`} data-clickable="true" onClick={() => openItem(r.case_id, r.item_id, false)}>
                <td className="mono">{r.case_id}</td>
                <td className="mono muted">{r.item_id ?? t('curation.target.case')}</td>
                <td>{r.item ? <PhaseChip phase={r.item.phase.canonical} /> : null}</td>
                <td className="mono">{r.target}</td>
                <td><StatusBadge status={r.status} /></td>
                <td>
                  <span className="badge" data-tone={r.priority === 'high' ? 'error' : r.priority === 'medium' ? 'warn' : undefined}>{t(`priority.${r.priority}`)}</span>
                </td>
                <td style={{ whiteSpace: 'normal', maxWidth: 360 }}>{r.comment}</td>
                <td className="muted">{t('curation.byAt', { reviewer: r.reviewer, ago: fmtAgo(r.at) })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  )
}
