// History (CUR-14): curation events for the active item or case, newest first
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useEvents } from '../../api'
import { StatusBadge, fmtAgo, fmtDate } from '../../lib'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'

export function HistoryList({ dense }: { dense?: boolean }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  const cid = useViewerSync((s) => s.activeCaseId)
  const [scope, setScope] = useState<'item' | 'case'>('case')
  const f = scope === 'item' && iid ? { item_id: iid } : cid ? { case_id: cid } : {}
  const { data, isLoading } = useEvents(pid, f)
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
      {data?.length === 0 ? <div className="empty">{t('history.empty')}</div> : null}
      <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {data?.map((e) => (
          <li key={e.event_id} style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '6px 12px', borderBottom: '1px solid var(--border-muted)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <StatusBadge status={e.status} />
              <span className="mono muted">{e.target}</span>
              {e.item_id ? <span className="mono muted">{e.item_id}</span> : null}
              <span className="muted" style={{ marginLeft: 'auto' }} title={fmtDate(e.at)}>
                {t('curation.byAt', { reviewer: e.reviewer, ago: fmtAgo(e.at) })}
              </span>
            </div>
            {e.comment ? <div>{e.comment}</div> : null}
            {e.proposed_phase ? <div className="muted">{t('history.proposedPhase', { phase: e.proposed_phase })}</div> : null}
            {e.add_to_queue ? <div className="muted">{t('history.queued')}</div> : null}
          </li>
        ))}
      </ol>
    </div>
  )
}

export const HistoryView = () => <HistoryList />
export const HistoryPanel = () => <HistoryList dense />
