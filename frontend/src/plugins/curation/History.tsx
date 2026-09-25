// History (CUR-14): curation events for the active item or case, newest first
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useEvents } from '../../api'
import { StatusBadge, fmtAgo, fmtDate } from '../../lib'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import '../../i18n/lazy'

export function HistoryList({ dense }: { dense?: boolean }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  const cid = useViewerSync((s) => s.activeCaseId)
  const [scope, setScope] = useState<'item' | 'case'>('case')
  const f = scope === 'item' && iid ? { item_id: iid } : cid ? { case_id: cid } : {}
  const { data, isLoading, isError } = useEvents(pid, f)
  if (!cid) return <div className="empty">{t('history.noActive')}</div>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', fontSize: 'var(--fs-panel)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: dense ? '4px 8px' : '0 12px 8px' }}>
        <div className="seg" role="group" aria-label={t('history.scope')}>
          <button type="button" aria-pressed={scope === 'case'} onClick={() => setScope('case')}>{t('history.case', { id: cid })}</button>
          <button type="button" aria-pressed={scope === 'item'} disabled={!iid} onClick={() => setScope('item')}>{t('history.item')}</button>
        </div>
      </div>
      {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
      {isError ? <div className="error-card">{t('history.error')}</div> : null}
      {data?.length === 0 ? <div className="empty">{t('history.empty')}</div> : null}
      <ol style={{ listStyle: 'none', margin: 0, padding: 0 }} aria-label={t('history.list')}>
        {data?.map((e) => (
          <li key={e.event_id} style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '6px 12px', borderBottom: '1px solid var(--border-muted)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <StatusBadge status={e.status} />
              <span className="mono muted">{e.target}</span>
              {e.item_id ? <span className="mono muted">{e.item_id}</span> : null}
              {e.priority !== 'medium' ? <span className="badge" data-tone={e.priority === 'high' ? 'error' : undefined}>{t(`priority.${e.priority}`)}</span> : null}
              {e.source === 'v2_import' ? <span className="badge">{t('history.v2Import')}</span> : null}
              <span className="muted" style={{ marginLeft: 'auto' }} title={fmtDate(e.at)}>
                {t('curation.byAt', { reviewer: e.reviewer, ago: fmtAgo(e.at) })}
              </span>
            </div>
            {e.comment ? <div>{e.comment}</div> : null}
            {e.proposed_side ? <div className="muted">{t('history.proposedSide', { side: e.proposed_side })}</div> : null}
            {e.context.viewer ? <div className="muted mono">{t('history.viewer', { axis: e.context.viewer.axis, slice: e.context.viewer.slice })}</div> : null}
            {e.add_to_queue ? <div className="muted">{t('history.queued')}</div> : null}
          </li>
        ))}
      </ol>
    </div>
  )
}

export const HistoryView = () => <HistoryList />
export const HistoryPanel = () => <HistoryList dense />
