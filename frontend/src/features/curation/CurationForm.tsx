// Curation decision form (CUR-03..07): target, one-click statuses, priority, comment, queue, proposals.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { create } from 'zustand'

import i18n from '../../i18n'
import {
  api,
  PHASES,
  useCurationState,
  useItem,
  useProject,
  type CurationStatus,
  type ItemRecord,
  type Phase,
  type Priority,
} from '../../api'
import { StatusBadge, StatusIcon, fmtAgo } from '../../lib'
import { bindingOf, formatChord, registry, toast, useWorkbench } from '../../shell'
import { requireReviewer, useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'

// Draft shared by the left view, the inspector and the keyboard shortcuts
interface Draft {
  target: string
  priority: Priority
  comment: string
  addToQueue: boolean
  proposedPhase: Phase | ''
  proposedSide: 'L' | 'R' | ''
  set: (p: Partial<Omit<Draft, 'set' | 'reset'>>) => void
  reset: () => void
}
export const useDraft = create<Draft>()((set) => ({
  target: 'seg',
  priority: 'medium',
  comment: '',
  addToQueue: false,
  proposedPhase: '',
  proposedSide: '',
  set: (p) => set(p),
  reset: () => set({ comment: '', addToQueue: false, proposedPhase: '', proposedSide: '' }),
}))

export const QUICK: { status: CurationStatus; cmd: string; tone: string }[] = [
  { status: 'accepted', cmd: 'curation.accept', tone: 'ok' },
  { status: 'needs_minor_correction', cmd: 'curation.minor', tone: 'warn' },
  { status: 'needs_major_correction', cmd: 'curation.major', tone: 'error' },
  { status: 'rejected', cmd: 'curation.reject', tone: 'error' },
]
const MORE: CurationStatus[] = ['wrong_phase_suspected', 'wrong_side_suspected', 'missing', 'cannot_assess', 'not_reviewed']

const chord = (id: string) => {
  const c = registry.commands.get(id)
  return c ? formatChord(bindingOf(c)) : ''
}

/** Append a decision for the active item using the current draft. Used by buttons and shortcuts.
 *  Caches refresh through the `curation.appended` server event (useProjectEvents). */
export async function submitDecision(status: CurationStatus, over: { addToQueue?: boolean } = {}) {
  const t = i18n.t.bind(i18n)
  const pid = useWorkbench.getState().pid
  const { activeItemId, activeCaseId, ww, wl } = useViewerSync.getState()
  const d = useDraft.getState()
  if (!pid || !activeCaseId) return
  const caseTarget = d.target === 'case'
  try {
    const reviewer = await requireReviewer()
    if (!reviewer) return
    await api.appendEvent(
      pid,
      {
        item_id: caseTarget ? null : activeItemId,
        case_id: activeCaseId,
        target: d.target,
        status,
        priority: d.priority,
        comment: d.comment,
        add_to_queue: over.addToQueue ?? d.addToQueue,
        proposed_phase: d.proposedPhase || null,
        proposed_side: d.proposedSide || null,
        context: { viewer: { axis: 'axial', slice: 24, ww, wl } },
      },
      reviewer,
    )
    d.reset()
    toast({ message: t('curation.saved', { status: t(`status.${status}`), target: d.target, id: activeItemId ?? activeCaseId }), tone: 'ok' })
  } catch {
    toast({ message: t('common.saveFailed'), tone: 'error' })
  }
}

function targets(item: ItemRecord | undefined, labels: { value: number; name: string }[]) {
  const out = [{ v: 'seg', l: 'curation.target.seg' }]
  for (const l of labels) out.push({ v: `label:${l.value}`, l: `label:${l.name}` })
  if (item?.scope === 'voi') out.push({ v: 'voi_mask', l: 'curation.target.voi_mask' })
  out.push({ v: 'phase', l: 'curation.target.phase' }, { v: 'side', l: 'curation.target.side' }, { v: 'case', l: 'curation.target.case' })
  return out
}

export function CurationForm({ compact }: { compact?: boolean }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  const cid = useViewerSync((s) => s.activeCaseId)
  const item = useItem(pid, iid).data
  const labels = useProject(pid).data?.label_map ?? []
  const state = useCurationState(pid).data ?? []
  const d = useDraft()
  const [busy, setBusy] = useState(false)
  if (!cid) return <div className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('curation.noActive')}</div>

  const mine = state.filter((s) => (s.item_id === iid && iid) || (s.item_id === null && s.case_id === cid))
  const go = async (s: CurationStatus) => {
    setBusy(true)
    await submitDecision(s)
    setBusy(false)
  }
  const showPhase = d.target === 'phase'
  const showSide = d.target === 'side'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 'var(--fs-panel)' }}>
      <div className="muted mono" style={{ fontSize: 'var(--fs-badge)' }}>{iid ?? cid}</div>
      <label className="field">
        <span className="field-label">{t('curation.target.label')}</span>
        <select className="select input-sm" value={d.target} onChange={(e) => d.set({ target: e.target.value })}>
          {targets(item, labels).map((o) => (
            <option key={o.v} value={o.v}>
              {o.l.startsWith('label:') ? t('curation.target.labelName', { name: o.l.slice(6) }) : t(o.l)}
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
      {showPhase ? (
        <label className="field">
          <span className="field-label">{t('curation.proposedPhase')}</span>
          <select className="select input-sm" value={d.proposedPhase} onChange={(e) => d.set({ proposedPhase: e.target.value as Phase | '' })}>
            <option value="">{t('common.none')}</option>
            {PHASES.map((p) => (
              <option key={p} value={p}>{t('search.phaseOption', { code: p, name: t(`phase.${p}`) })}</option>
            ))}
          </select>
        </label>
      ) : null}
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
      {mine.length ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div className="section-title" style={{ padding: 0 }}>{t('curation.current')}</div>
          {mine.map((s) => (
            <div key={`${s.item_id}|${s.target}`} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <span className="mono muted">{s.target}</span>
              <StatusBadge status={s.status} />
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
