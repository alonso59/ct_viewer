// Case editor tab: item switcher + the NiiVue viewer (VIEWER.md; VW-11, 12, 14).
import { useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { api, useCase, useProject, useSegmentations, viewPath, type ItemRecord, type LabelDef, type Phase } from '../../api'
import { PhaseChip, StatusBadge } from '../../lib'
import { pinEditor, updateActiveParams, useWorkbench, type EditorProps } from '../../shell'
import { PhaseButtons, PhaseHistoryButton } from '../phase'
import { useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { useLoadBudget } from './budget'
import { ViewerSurface, viewerFocusProps } from './ViewerSurface'
import './viewer.css'

export interface CaseParams {
  caseId: string
  itemId: string | null
  preview?: boolean
}

/** API-23/24/25 (volumes are streamed as the original bytes, BE-04) */
const API = '/api/v1'
export const itemUrl = (pid: string, iid: string, what: 'image' | 'mask') => viewPath(`${API}/projects/${encodeURIComponent(pid)}/items/${encodeURIComponent(iid)}/${what}`)
export const meshUrlOf = (pid: string, iid: string, seg?: string) => (label: number) =>
  viewPath(`${API}/projects/${encodeURIComponent(pid)}/items/${encodeURIComponent(iid)}/mesh/${label}?smooth=1${seg ? `&seg=${encodeURIComponent(seg)}` : ''}`)

/** VW-19: overlay labels for a set: its values coloured by the project labels they map to */
export function setLabels(labels: LabelDef[], mapping: Record<string, number> | undefined): LabelDef[] {
  const entries = Object.entries(mapping ?? {})
  if (!entries.length || entries.every(([k, v]) => Number(k) === v)) return labels
  return entries.flatMap(([k, v]) => {
    const l = labels.find((x) => x.value === v)
    return l ? [{ ...l, value: Number(k) }] : []
  })
}

/** Warning codes that mean the image cannot be opened at all (IMP-08) */
export const FATAL_CODES = ['missing_path', 'unreadable_file', 'outside_root']

export function defaultItem(items: ItemRecord[]): ItemRecord | undefined {
  const complete = items.filter((i) => i.scope === 'complete' && i.status !== 'excluded_upstream')
  return complete.find((i) => i.phase.canonical === 'NP' && i.status === 'active') ?? complete.find((i) => i.status === 'active') ?? items[0]
}

function ItemSwitcher({ items, current, onPick }: { items: ItemRecord[]; current: ItemRecord; onPick: (id: string) => void }) {
  const { t } = useTranslation()
  const phases = [...new Set(items.map((i) => i.phase.canonical))] as Phase[]
  const inPhase = items.filter((i) => i.phase.canonical === current.phase.canonical)
  const scans = [...new Set(inPhase.map((i) => i.scan_idx))]
  const inScan = inPhase.filter((i) => i.scan_idx === current.scan_idx)
  const hasVoi = inScan.some((i) => i.scope === 'voi')
  const sides = inScan.filter((i) => i.scope === 'voi').map((i) => i.side)
  const pick = (f: (i: ItemRecord) => boolean) => {
    const target = items.find((i) => f(i) && i.scope === current.scope && i.side === current.side) ?? items.find(f)
    if (target) onPick(target.item_id)
  }
  return (
    <div className="switcher" role="toolbar" aria-label={t('viewer.itemSwitcher')}>
      <span className="switcher-label">{t('viewer.phase')}</span>
      {phases.map((p) => (
        <PhaseChip key={p} phase={p} active={p === current.phase.canonical} onClick={() => pick((i) => i.phase.canonical === p)} />
      ))}
      {scans.length > 1 ? (
        <>
          <span className="switcher-sep" />
          <span className="switcher-label">{t('viewer.scan')}</span>
          {scans.map((s) => (
            <button key={s} type="button" className="badge" aria-pressed={s === current.scan_idx} data-tone={s === current.scan_idx ? 'accent' : undefined} onClick={() => pick((i) => i.phase.canonical === current.phase.canonical && i.scan_idx === s)}>
              {s}
            </button>
          ))}
        </>
      ) : null}
      <span className="switcher-sep" />
      <div className="seg" role="group" aria-label={t('viewer.scope')}>
        <button type="button" aria-pressed={current.scope === 'complete'} onClick={() => pick((i) => i.phase.canonical === current.phase.canonical && i.scan_idx === current.scan_idx && i.scope === 'complete')}>
          {t('item.full')}
        </button>
        <button type="button" aria-pressed={current.scope === 'voi'} disabled={!hasVoi} onClick={() => pick((i) => i.phase.canonical === current.phase.canonical && i.scan_idx === current.scan_idx && i.scope === 'voi')}>
          {t('item.voi')}
        </button>
      </div>
      {current.scope === 'voi' ? (
        <div className="seg" role="group" aria-label={t('viewer.side')}>
          {sides.map((s) => (
            <button key={s} type="button" aria-pressed={current.side === s} onClick={() => pick((i) => i.phase.canonical === current.phase.canonical && i.scan_idx === current.scan_idx && i.scope === 'voi' && i.side === s)}>
              {s}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function CaseEditor({ params, panelId, active }: EditorProps<CaseParams>) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, isLoading, isError, error } = useCase(pid, params.caseId)
  const project = useProject(pid)
  const set = useViewerSync((s) => s.set)
  const loaded = useLoadBudget(panelId, active)

  const items = useMemo(() => data?.items ?? [], [data])
  const current = items.find((i) => i.item_id === params.itemId) ?? defaultItem(items)
  const iid = current?.item_id ?? ''
  // VW-19: the active segmentation set (Layers section), else the project's default
  const activeSeg = useViewerSync((s) => s.activeSeg)
  const segId = activeSeg ?? project.data?.default_seg ?? 'imported'
  const sets = useSegmentations(pid).data
  const mapping = sets?.find((s) => s.seg_id === segId)?.label_mapping
  const meshUrl = useMemo(() => meshUrlOf(pid, iid, segId), [pid, iid, segId])
  const labels = useMemo(() => setLabels(project.data?.label_map ?? [], mapping), [project.data, mapping])
  const shown = useMemo(() => (current ? { ...current, mask: current.masks[segId] ?? null } : null), [current, segId])

  useEffect(() => {
    if (active && current) set({ activeCaseId: params.caseId, activeItemId: current.item_id })
  }, [active, current, params.caseId, set])

  const pick = (itemId: string) => {
    updateActiveParams(panelId, { itemId })
    pinEditor(panelId)
  }

  if (isLoading) return <div className="empty">{t('common.loading')}</div>
  if (isError || !data || !current)
    return (
      <div className="error-card" role="alert">
        <strong>{(error as { title?: string } | null)?.title ?? t('viewer.caseNotFound')}</strong>
      </div>
    )

  const fatal = current.warning_codes.find((c) => FATAL_CODES.includes(c))

  return (
    <div className="case-editor" {...viewerFocusProps}>
      <div className="case-header">
        <span className="mono case-id">{params.caseId}</span>
        <ItemSwitcher items={items.filter((i) => i.status !== 'excluded_upstream')} current={current} onPick={pick} />
        {/* PHS-01: set this scan's phase (the switcher's chips only move between scans) */}
        <span className="switcher-sep" />
        <span className="switcher-label">{t('phaseSel.set')}</span>
        <PhaseButtons pid={pid} scan={current} />
        <PhaseHistoryButton pid={pid} caseId={current.case_id} scanIdx={current.scan_idx} />
        <span style={{ flex: 1 }} />
        {current.warning_codes.length ? (
          <span className="badge" data-tone="warn" title={current.warning_codes.join(', ')}>
            <Icon spec={codicon('warning')} />
            {current.warning_codes.length}
          </span>
        ) : null}
        <StatusBadge status={data.summary.curation_status} />
      </div>
      {fatal || current.status === 'missing' ? (
        <div className="error-card" role="alert" style={{ maxWidth: 560 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ color: 'var(--error)', display: 'inline-flex' }}>
              <Icon spec={codicon('error')} />
            </span>
            <strong>{t(`warning.${fatal ?? 'missing_path'}`)}</strong>
            <span className="badge mono">{fatal ?? 'missing_path'}</span>
          </div>
          <div className="muted">{t('viewer.fileError', { ref: current.image?.ref ?? '—' })}</div>
        </div>
      ) : (
        <ViewerSurface
          item={shown ?? current}
          imageUrl={itemUrl(pid, current.item_id, 'image')}
          maskUrl={current.masks[segId] ? `${itemUrl(pid, current.item_id, 'mask')}?seg=${encodeURIComponent(segId)}` : undefined}
          labels={labels}
          meshUrl={meshUrl}
          active={active}
          loaded={loaded}
          tags={current.extra.dicom_sidecar ? () => api.dicomTags(pid, current.item_id) : undefined}
        />
      )}
    </div>
  )
}
