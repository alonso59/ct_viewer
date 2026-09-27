// Shared view plumbing: frame with loading/error states and exports (FE-09, DB-06), item context
// menu (DASHBOARD §Interaction with curation), colours (DB-07), pickers and focus requests (DB-09).
import * as Menu from '@radix-ui/react-dropdown-menu'
import type { UseQueryResult } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { create } from 'zustand'

import {
  CURATION_STATUSES,
  ProblemError,
  ReviewerCancelled,
  useAppendEvent,
  useCurationState,
  useDashboardView,
  useProject,
  useVariables,
  type ColorBy,
  type CurationStatus,
  type DashboardView,
  type UnitSpec,
  type Variable,
} from '../../../api'
import { itemName, knownPhase } from '../../../lib'
import { toast, useWorkbench } from '../../../shell'
import { Icon, codicon, token } from '../../../theme'
import { openInContext, openItem } from '../../../features/explorer'
import { palette, type ChartInstance } from '../Chart'
import { useDashboardStore, useRunDashboard } from '../store'

export interface ViewProps {
  runId: string
}

export const usePid = () => useWorkbench((s) => s.pid) ?? ''

export function asStatus(s: string | null | undefined): CurationStatus {
  return (CURATION_STATUSES as readonly string[]).includes(s ?? '') ? (s as CurationStatus) : 'not_reviewed'
}

// ---- exports (DB-06) ---------------------------------------------------------------------------
function download(name: string, href: string) {
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.click()
}
export type CsvRows = (string | number | null | undefined)[][]
export function downloadCsv(name: string, rows: CsvRows) {
  const esc = (v: string | number | null | undefined) => {
    const s = v == null ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
  }
  const url = URL.createObjectURL(new Blob([`${rows.map((r) => r.map(esc).join(',')).join('\n')}\n`], { type: 'text/csv' }))
  download(`${name}.csv`, url)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function downloadPng(name: string, chart: ChartInstance) {
  download(`${name}.png`, chart.getDataURL({ pixelRatio: 2, backgroundColor: token('--bg-editor') }))
}

function ProblemState({ error }: { error: unknown }) {
  const { t } = useTranslation()
  const p = error instanceof ProblemError ? error : null
  return (
    <div className="error-card db-error" role="alert">
      <strong>{p?.title ?? t('common.error')}</strong>
      {p?.detail ? <div className="muted">{p.detail}</div> : null}
    </div>
  )
}

/** Toolbar (controls + exports) and the loading / error / empty states around a view body */
export function ViewFrame({ name, controls, chart, csv, query, empty, children }: {
  name: string
  controls?: ReactNode
  chart?: ChartInstance | null
  csv?: () => CsvRows
  query?: Pick<UseQueryResult<unknown>, 'isLoading' | 'error' | 'data' | 'isFetching'>
  /** Shown instead of the body when set (e.g. "pick a variable") */
  empty?: string | null
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const failed = query?.error && !query.data
  return (
    <div className="db-view">
      <div className="db-view-bar">
        <div className="db-view-controls">{controls}</div>
        {query?.isFetching ? <span className="muted db-busy" aria-live="polite">{t('common.loading')}</span> : null}
        {chart ? (
          <button type="button" className="icon-btn" title={t('dashboard.exportPng')} aria-label={t('dashboard.exportPng')} onClick={() => downloadPng(name, chart)}>
            <Icon spec={codicon('device-camera')} />
          </button>
        ) : null}
        {csv ? (
          <button type="button" className="icon-btn" title={t('dashboard.exportCsv')} aria-label={t('dashboard.exportCsv')} disabled={!query?.data} onClick={() => downloadCsv(name, csv())}>
            <Icon spec={codicon('export')} />
          </button>
        ) : null}
      </div>
      <div className="db-view-body">
        {empty ? <div className="empty">{empty}</div> : failed ? <ProblemState error={query.error} /> : query?.isLoading ? <div className="empty">{t('common.loading')}</div> : children}
      </div>
    </div>
  )
}

// ---- focus requests (DB-09) ----------------------------------------------------------------------
/** Apply params from `focusView(runId, view, params)` once per request */
export function useFocusParams(runId: string, view: DashboardView, apply: (params: Record<string, unknown>) => void) {
  const focus = useRunDashboard(runId).focus
  const seen = useRef(0)
  const fn = useRef(apply)
  useEffect(() => {
    fn.current = apply
  })
  useEffect(() => {
    if (focus && focus.view === view && focus.nonce !== seen.current) {
      seen.current = focus.nonce
      fn.current(focus.params)
    }
  }, [focus, view])
}
export const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
export const numParam = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

// ---- features and variables ---------------------------------------------------------------------
const FEATURE_LIST_BODY = { max_cells: 1 }

/** Feature names of the run (full names as API-38 uses them), grouped by class */
export function useFeatureNames(runId: string): { name: string; cls: string }[] {
  const pid = usePid()
  const q = useDashboardView(pid, runId, 'missing-matrix', FEATURE_LIST_BODY)
  return useMemo(() => (q.data?.features ?? []).map((f) => ({ name: f.feature, cls: f.feature_class })), [q.data])
}

export const DEFAULT_FEATURE = 'original_firstorder_Mean'

export function pickFeature(names: { name: string }[], wanted: string | null): string | null {
  if (wanted && names.some((n) => n.name === wanted)) return wanted
  return names.find((n) => n.name === DEFAULT_FEATURE)?.name ?? names[0]?.name ?? wanted
}

export function FeatureSelect({ runId, value, onChange, exclude }: { runId: string; value: string | null; onChange: (f: string) => void; exclude?: string }) {
  const { t } = useTranslation()
  const names = useFeatureNames(runId)
  const classes = [...new Set(names.map((n) => n.cls))]
  return (
    <select className="select input-sm db-feature" value={value ?? ''} onChange={(e) => onChange(e.target.value)} aria-label={t('dashboard.feature')}>
      {classes.map((c) => (
        <optgroup key={c} label={c}>
          {names.filter((n) => n.cls === c && n.name !== exclude).map((n) => (
            <option key={n.name} value={n.name}>{n.name}</option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

/** Visible variables usable for grouping (categorical) or association (continuous) */
export function useVisibleVariables(kind?: 'categorical' | 'continuous'): Variable[] {
  const pid = usePid()
  const vars = useVariables(pid).data
  return useMemo(() => (vars ?? []).filter((v) => v.visible && (kind ? v.type === kind : v.type === 'categorical' || v.type === 'continuous' || v.type === 'numeric-discrete')), [vars, kind])
}

export function VariableSelect({ kind, value, onChange, label, exclude }: {
  kind: 'categorical' | 'continuous'
  value: string | null
  onChange: (v: string) => void
  label: string
  exclude?: string | null
}) {
  const { t } = useTranslation()
  const vars = useVisibleVariables(kind).filter((v) => v.name !== exclude)
  return (
    <select className="select input-sm" value={value ?? ''} onChange={(e) => onChange(e.target.value)} aria-label={label}>
      <option value="" disabled>{t('dashboard.pickVariable')}</option>
      {vars.map((v) => (
        <option key={v.name} value={v.name}>{v.name}</option>
      ))}
    </select>
  )
}

// ---- colours and level names (DB-07) ------------------------------------------------------------
/** Level → colour from the categorical palette; missing levels use the muted token */
export function useLevelColors(levels: (string | null)[]): (level: string | null | undefined) => string {
  return useMemo(() => {
    const colors = palette()
    const muted = token('--fg-muted')
    const order = [...new Set(levels.filter((l): l is string => l !== null))]
    return (level) => {
      const i = level == null ? -1 : order.indexOf(level)
      return i < 0 ? muted : (colors[i % colors.length] ?? muted)
    }
  }, [levels])
}

/** Display name of a colour/split level */
export function useLevelName(colorBy: ColorBy | null | undefined): (level: string | null | undefined) => string {
  const { t } = useTranslation()
  const labels = useProject(usePid()).data?.label_map
  const kind = colorBy?.kind
  return useCallback(
    (level) => {
      if (level == null || level === '') return t('dashboard.missingLevel')
      if (kind === 'curation_status') return t(`status.${asStatus(level)}`)
      if (kind === 'label') return labels?.find((l) => String(l.value) === level)?.name ?? level
      return level
    },
    [t, kind, labels],
  )
}

export function useLabelName(): (label: number) => string {
  const labels = useProject(usePid()).data?.label_map
  return useCallback((label) => labels?.find((l) => l.value === label)?.name ?? String(label), [labels])
}

/** Point style for the linked selection (DB-04): selected points stand out, others dim */
export function useSelection(runId: string) {
  const selection = useRunDashboard(runId).selection
  const select = useDashboardStore((s) => s.select)
  return useMemo(() => {
    const set = new Set(selection)
    const fg = token('--fg')
    return {
      selected: set,
      any: set.size > 0,
      select: (ids: string[]) => select(runId, ids),
      style: (id: string, color: string) =>
        set.size === 0 ? { color, opacity: 0.85 } : set.has(id) ? { color, opacity: 1, borderColor: fg, borderWidth: 1.5 } : { color, opacity: 0.2 },
    }
  }, [selection, select, runId])
}

// ---- item context menu -------------------------------------------------------------------------
export interface ItemRef {
  item_id: string
  case_id: string
}
interface ItemMenuState {
  target: (ItemRef & { x: number; y: number }) | null
  open: (item: ItemRef, x: number, y: number) => void
  close: () => void
}
export const useItemMenu = create<ItemMenuState>()((set) => ({
  target: null,
  open: (item, x, y) => set({ target: { ...item, x, y } }),
  close: () => set({ target: null }),
}))

/** DB-03 click: open the item in a case tab */
export const openRef = (r: ItemRef | undefined) => r && openItem(r.case_id, r.item_id, true)

/** Mounted once per dashboard: Open in viewer · Add to correction queue · Copy item_id */
export function ItemMenu() {
  const { t } = useTranslation()
  const pid = usePid()
  const target = useItemMenu((s) => s.target)
  const close = useItemMenu((s) => s.close)
  const state = useCurationState(pid).data
  const defaultSeg = useProject(pid).data?.default_seg ?? 'imported'
  const append = useAppendEvent(pid)
  if (!target) return null
  const addToQueue = () => {
    // Q semantics (CUR-09): keep the item's current `seg` status, flag it for the queue; the event
    // carries no seg_id, so it is about `default_seg` (ADR-0015, AUD-A5-06)
    const current = state?.find((r) => r.item_id === target.item_id && r.target === 'seg' && (r.seg_id ?? 'imported') === defaultSeg)?.status ?? 'not_reviewed'
    append.mutate(
      { item_id: target.item_id, case_id: target.case_id, target: 'seg', status: current, priority: 'medium', comment: '', add_to_queue: true },
      {
        onSuccess: () => toast({ message: t('dashboard.menu.queued', { id: itemName(target.item_id, t, knownPhase(pid, target.item_id)) }), tone: 'ok' }),
        onError: (e) => {
          if (!(e instanceof ReviewerCancelled)) toast({ message: t('common.saveFailed'), tone: 'error' })
        },
      },
    )
  }
  const copy = () => {
    const done = () => toast({ message: t('dashboard.menu.copied', { id: target.item_id }), tone: 'ok' })
    if (navigator.clipboard) navigator.clipboard.writeText(target.item_id).then(done, () => toast({ message: target.item_id }))
    else toast({ message: target.item_id })
  }
  return (
    <Menu.Root open onOpenChange={(o) => !o && close()} modal={false}>
      <Menu.Trigger asChild>
        <span aria-hidden style={{ position: 'fixed', left: target.x, top: target.y, width: 1, height: 1 }} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" align="start" sideOffset={2}>
          <Menu.Label className="menu-label" title={target.item_id}>{itemName(target.item_id, t, knownPhase(pid, target.item_id))}</Menu.Label>
          <Menu.Item className="menu-item" onSelect={() => openRef(target)}>
            <Icon spec={codicon('eye')} />
            {t('dashboard.openInViewer')}
          </Menu.Item>
          <Menu.Item className="menu-item" onSelect={addToQueue}>
            <Icon spec={codicon('checklist')} />
            {t('dashboard.menu.addToQueue')}
          </Menu.Item>
          <Menu.Item className="menu-item" onSelect={copy}>
            <Icon spec={codicon('copy')} />
            {t('dashboard.menu.copyId')}
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}

/** Row props for tables of items: click opens, right click shows the item menu, selection highlight.
 *  `list` (label + all rows): the case tab follows that list on Alt+↓ (AUD-A1-04). */
export function rowProps(r: ItemRef, selected: Set<string>, list?: { label: string; rows: ItemRef[] }) {
  return {
    'data-clickable': 'true',
    'aria-selected': selected.has(r.item_id) || undefined,
    onClick: () =>
      list
        ? openInContext(list.label, list.rows.map((x) => ({ caseId: x.case_id, itemId: x.item_id })), list.rows.indexOf(r), true)
        : openRef(r),
    onContextMenu: (e: ReactMouseEvent) => {
      e.preventDefault()
      useItemMenu.getState().open(r, e.clientX, e.clientY)
    },
  }
}

/** Unit of analysis (ANA-03) follows a single-label filter; otherwise the server default */
export function unitFor(labels: number[] | null | undefined): UnitSpec {
  return { aggregate: 'first', ...(labels?.length === 1 ? { label: labels[0] } : {}) }
}
