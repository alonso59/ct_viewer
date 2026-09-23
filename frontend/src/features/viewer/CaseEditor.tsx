// Case editor tab: item switcher + 2×2 viewer placeholder (VIEWER.md; VW-01, 02, 04, 11, 12, 13).
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { loadSlices, useCase, useProject, type ItemRecord, type Phase, type SliceSet } from '../../api'
import { PhaseChip, Progress, StatusBadge } from '../../lib'
import { pinEditor, updateActiveParams, useWorkbench, type EditorProps } from '../../shell'
import { useViewerSync, type LayoutId, type ViewportId } from '../../state'
import { Icon, codicon } from '../../theme'
import { Viewport } from './Viewport'
import './viewer.css'

export interface CaseParams {
  caseId: string
  itemId: string | null
  preview?: boolean
}

const LAYOUTS: Record<LayoutId, ViewportId[]> = {
  'four-up': ['axial', 'sagittal', 'coronal', '3d'],
  conventional: ['axial', 'sagittal', 'coronal', '3d'],
  'three-mpr': ['axial', 'sagittal', 'coronal'],
  'one-up-axial': ['axial'],
  'one-up-sagittal': ['sagittal'],
  'one-up-coronal': ['coronal'],
  'one-up-3d': ['3d'],
}

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

/** VW-13 loading UI: simulated download progress; remounts per item */
function LoadBar() {
  const [progress, setProgress] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setProgress((p) => Math.min(100, p + 25)), 60)
    return () => clearInterval(id)
  }, [])
  if (progress >= 100) return null
  return (
    <div className="case-loading">
      <Progress value={progress} total={100} />
    </div>
  )
}

export function CaseEditor({ params, panelId, active }: EditorProps<CaseParams>) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, isLoading, isError, error } = useCase(pid, params.caseId)
  const project = useProject(pid)
  const layout = useViewerSync((s) => s.layout)
  const maximized = useViewerSync((s) => s.maximized)
  const set = useViewerSync((s) => s.set)
  const [slices, setSlices] = useState<Map<string, SliceSet> | null>(null)

  const items = useMemo(() => data?.items ?? [], [data])
  const current = items.find((i) => i.item_id === params.itemId) ?? defaultItem(items)

  useEffect(() => {
    void loadSlices().then(setSlices)
  }, [])

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

  const labels = project.data?.label_map ?? []
  const sliceSet = slices ? (slices.get(current.item_id) ?? undefined) : null
  const viewports = maximized ? [maximized] : LAYOUTS[layout]
  const fatal = current.warning_codes.find((c) => ['missing_path', 'unreadable_file', 'outside_root'].includes(c))

  return (
    <div
      className="case-editor"
      tabIndex={-1}
      onFocus={() => set({ viewerFocused: true })}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) set({ viewerFocused: false })
      }}
      onPointerDown={(e) => {
        if (!(e.target as HTMLElement).closest('button, input, select')) e.currentTarget.focus()
      }}
    >
      <div className="case-header">
        <span className="mono case-id">{params.caseId}</span>
        <ItemSwitcher items={items.filter((i) => i.status !== 'excluded_upstream')} current={current} onPick={pick} />
        <span style={{ flex: 1 }} />
        {current.warning_codes.length ? (
          <span className="badge" data-tone="warn" title={current.warning_codes.join(', ')}>
            <Icon spec={codicon('warning')} />
            {current.warning_codes.length}
          </span>
        ) : null}
        <StatusBadge status={data.summary.curation_status} />
      </div>
      {!fatal ? <LoadBar key={current.item_id} /> : null}
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
        <div className={`vp-grid vp-grid-${maximized ? 'one' : layout}`}>
          {viewports.map((id) => (
            <Viewport
              key={id}
              id={id}
              item={current}
              slices={sliceSet}
              labels={labels}
              maximized={maximized === id}
              onMaximize={() => set({ maximized: maximized === id ? null : id })}
            />
          ))}
        </div>
      )}
    </div>
  )
}
