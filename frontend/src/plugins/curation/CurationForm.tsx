// Curation decision form (CUR-03..07): target, one-click statuses, priority, comment, queue, proposals.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useCurationState, useItem, useProject, type CurationStatus, type Priority } from '../../api'
import { StatusBadge, StatusIcon, fmtAgo } from '../../lib'
import { bindingOf, formatChord, registry, useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { submitDecision, useDraft } from './decision'
import { decisionsFor, targetsFor } from './model'
import '../../i18n/lazy'

export const QUICK: { status: CurationStatus; cmd: string; tone: string }[] = [
  { status: 'accepted', cmd: 'curation.accept', tone: 'ok' },
  { status: 'needs_minor_correction', cmd: 'curation.minor', tone: 'warn' },
  { status: 'needs_major_correction', cmd: 'curation.major', tone: 'error' },
  { status: 'rejected', cmd: 'curation.reject', tone: 'error' },
]
const MORE: CurationStatus[] = ['wrong_side_suspected', 'missing', 'cannot_assess', 'not_reviewed']

const chord = (id: string) => {
  const c = registry.commands.get(id)
  return c ? formatChord(bindingOf(c)) : ''
}

export function CurationForm({ compact }: { compact?: boolean }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  const cid = useViewerSync((s) => s.activeCaseId)
  const item = useItem(pid, iid).data
  const project = useProject(pid).data
  const labels = project?.label_map ?? []
  const stateQ = useCurationState(pid)
  const d = useDraft()
  const [busy, setBusy] = useState(false)
  if (!cid) return <div className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('curation.noActive')}</div>

  const mine = decisionsFor(stateQ.data ?? [], iid, cid)
  const go = async (s: CurationStatus) => {
    setBusy(true)
    await submitDecision(s)
    setBusy(false)
  }
  const showSide = d.target === 'side'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 'var(--fs-panel)' }}>
      <div className="muted mono" style={{ fontSize: 'var(--fs-badge)' }}>{iid ?? cid}</div>
      <label className="field">
        <span className="field-label">{t('curation.target.label')}</span>
        <select className="select input-sm" value={d.target} onChange={(e) => d.set({ target: e.target.value })}>
          {targetsFor(item, labels).map((o) => (
            <option key={o.value} value={o.value} disabled={o.value !== 'case' && !iid}>
              {o.label.startsWith('label:') ? t('curation.target.labelName', { name: o.label.slice(6) }) : t(o.label)}
            </option>
          ))}
        </select>
      </label>
      <div style={{ display: 'grid', gridTemplateColumns: compact ? '1fr 1fr' : '1fr 1fr', gap: 6 }}>
        {QUICK.map((q) => (
          <button key={q.status} type="button" className="btn btn-sm" disabled={busy} onClick={() => void go(q.status)} style={{ justifyContent: 'flex-start' }}>
            <StatusIcon status={q.status} />
            {t(`statusShort.${q.status}`)}
            <span className="kbd" style={{ marginLeft: 'auto' }}>{chord(q.cmd)}</span>
          </button>
        ))}
      </div>
      <Menu.Root>
        <Menu.Trigger className="btn btn-sm" disabled={busy}>
          {t('curation.more')}
          <Icon spec={codicon('chevron-down')} />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="overlay menu" sideOffset={4} align="start">
            {MORE.map((s) => (
              <Menu.Item key={s} className="menu-item" onSelect={() => void go(s)}>
                <StatusIcon status={s} />
                {t(`status.${s}`)}
              </Menu.Item>
            ))}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      {showSide ? (
        <label className="field">
          <span className="field-label">{t('curation.proposedSide')}</span>
          <select className="select input-sm" value={d.proposedSide} onChange={(e) => d.set({ proposedSide: e.target.value as 'L' | 'R' | '' })}>
            <option value="">{t('common.none')}</option>
            <option value="L">{t('curation.sideL')}</option>
            <option value="R">{t('curation.sideR')}</option>
          </select>
        </label>
      ) : null}
      <div className="field">
        <span className="field-label">{t('curation.priority')}</span>
        <div className="seg" role="group">
          {(['low', 'medium', 'high'] as Priority[]).map((p) => (
            <button key={p} type="button" aria-pressed={d.priority === p} onClick={() => d.set({ priority: p })}>
              {t(`priority.${p}`)}
            </button>
          ))}
        </div>
      </div>
      <label className="field">
        <span className="field-label">{t('curation.comment')}</span>
        <textarea className="input" rows={3} value={d.comment} placeholder={t('curation.commentPlaceholder')} onChange={(e) => d.set({ comment: e.target.value })} />
      </label>
      <label className="check">
        <input type="checkbox" checked={d.addToQueue} onChange={(e) => d.set({ addToQueue: e.target.checked })} />
        {t('curation.addToQueue')}
        <span className="kbd" style={{ marginLeft: 'auto' }}>{chord('curation.queue')}</span>
      </label>
      {stateQ.isError ? <div className="error-card">{t('curation.stateError')}</div> : null}
      {mine.length ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }} role="list" aria-label={t('curation.current')}>
          <div className="section-title" style={{ padding: 0 }}>{t('curation.current')}</div>
          {mine.map((s) => (
            <div key={`${s.item_id ?? s.case_id}|${s.target}`} role="listitem" style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }} title={s.comment || undefined}>
              <span className="mono muted">{s.target}</span>
              <StatusBadge status={s.status} />
              {s.proposed_side ? <span className="muted">{t('history.proposedSide', { side: s.proposed_side })}</span> : null}
              {s.add_to_queue ? <span className="muted" title={t('history.queued')}><Icon spec={codicon('checklist')} /></span> : null}
              <span className="muted" style={{ marginLeft: 'auto', fontSize: 'var(--fs-badge)' }}>
                {t('curation.byAt', { reviewer: s.reviewer, ago: fmtAgo(s.at) })}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function InspectorCuration() {
  return <CurationForm compact />
}
