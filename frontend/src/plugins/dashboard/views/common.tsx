import * as Menu from '@radix-ui/react-dropdown-menu'
import type { UseQueryResult } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
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
import { fmtInt, fmtValue, itemName, knownPhase, useRowKeys } from '../../../lib'
import { toast, useWorkbench } from '../../../shell'
import { Icon, codicon, token } from '../../../theme'
import { openInContext, openItem } from '../../../features/explorer'
import { chartImage, palette, type ChartImageKind, type ChartInstance } from '../Chart'
import { useDashboardStore, useRunDashboard } from '../store'

export interface ViewProps {
  runId: string
}

export const usePid = () => useWorkbench((s) => s.pid) ?? ''

export function asStatus(s: string | null | undefined): CurationStatus {
  return (CURATION_STATUSES as readonly string[]).includes(s ?? '') ? (s as CurationStatus) : 'not_reviewed'
}

function download(name: string, href: string) {
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.click()
}
export type CsvRows = (string | number | null | undefined)[][]
function downloadCsv(name: string, rows: CsvRows) {
  const esc = (v: string | number | null | undefined) => {
    const s = v == null ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
  }
  const url = URL.createObjectURL(new Blob([`${rows.map((r) => r.map(esc).join(',')).join('\n')}\n`], { type: 'text/csv' }))
  download(`${name}.csv`, url)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
const IMAGE_FILES: Record<ChartImageKind, string> = { png: 'png', 'png-light': 'light.png', svg: 'svg' }
function downloadImage(name: string, chart: ChartInstance, kind: ChartImageKind) {
  download(`${name}.${IMAGE_FILES[kind]}`, chartImage(chart, kind))
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

/** While on, a view's charts show their rows as tables (default rows: the view's CSV) */
const TableMode = createContext<{ on: boolean; rows?: () => CsvRows }>({ on: false })

/** A chart, or its rows while the view shows tables. With `runId`, rows of items get a checkbox
 *  for the linked selection: the keyboard way to do what a brush does. */
export function ChartOrTable({ rows, runId, children }: { rows?: () => CsvRows; runId?: string; children: ReactNode }) {
  const mode = useContext(TableMode)
  const data = rows ?? mode.rows
  return mode.on && data ? <DataTable rows={data()} runId={runId} /> : children
}

/** Rows a table shows; the CSV keeps every row */
const TABLE_MAX = 1000

/** Rows (header first) as a table. Rows with an `item_id` and a `case_id` open their item (click,
 *  Enter) and have the item menu (right click, Shift+F10). */
function DataTable({ rows, runId }: { rows: CsvRows; runId?: string }) {
  const { t } = useTranslation()
  const [head = [], ...body] = rows
  const itemCol = head.indexOf('item_id')
  const caseCol = head.indexOf('case_id')
  const items = itemCol >= 0 && caseCol >= 0
  const shown = body.slice(0, TABLE_MAX)
  const rowKeys = useRowKeys(items ? shown.map((_, i) => String(i)) : [])
  const sel = useSelection(runId ?? '')
  const pick = items && runId !== undefined
  const toggle = (id: string, on: boolean) => sel.select(on ? [...sel.selected, id] : [...sel.selected].filter((x) => x !== id))
  return (
    <div className="db-table" tabIndex={0} role="region" aria-label={t('dashboard.table.label')}>
      {body.length > shown.length ? <p className="muted">{t('dashboard.table.capped', { shown: fmtInt(shown.length), total: fmtInt(body.length) })}</p> : null}
      <table className="table">
        <thead>
          <tr>
            {pick ? <th><span className="visually-hidden">{t('dashboard.table.select')}</span></th> : null}
            {head.map((h, i) => <th key={i}>{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => {
            const ref = items ? { item_id: String(r[itemCol] ?? ''), case_id: String(r[caseCol] ?? '') } : null
            return (
              <tr key={i} {...(ref ? { ...rowProps(ref, sel.selected), ...rowKeys(String(i)) } : {})}>
                {pick && ref ? (
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t('dashboard.table.selectItem', { id: ref.item_id })}
                      checked={sel.selected.has(ref.item_id)}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => toggle(ref.item_id, e.target.checked)}
                    />
                  </td>
                ) : null}
                {r.map((v, j) => (
                  <td key={j} className={typeof v === 'number' ? 'num' : undefined}>{typeof v === 'number' ? fmtValue(v) : (v ?? '—')}</td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Marks a value that a colour also marks: an icon to see, its words for screen readers */
export function ValueFlag({ tone, icon, label }: { tone: 'ok' | 'warn' | 'error'; icon: string; label: string }) {
  return (
    <span className="db-flag" style={{ color: `var(--${tone})` }} title={label}>
      <Icon spec={codicon(icon)} />
      <span className="visually-hidden">{label}</span>
    </span>
  )
}

/** Toolbar (controls + exports) and the loading / error / empty states around a view body. A view
 *  with a chart (`chart` given, null until drawn) can show its charts as tables instead. */
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
  const [asTable, setAsTable] = useState(false)
  const failed = query?.error && !query.data
  return (
    <div className="db-view">
      <div className="db-view-bar">
        <div className="db-view-controls">{controls}</div>
        {query?.isFetching ? <span className="muted db-busy" aria-live="polite">{t('common.loading')}</span> : null}
        {chart !== undefined ? (
          <button type="button" className="icon-btn" aria-pressed={asTable} title={t('dashboard.table.show')} aria-label={t('dashboard.table.show')} onClick={() => setAsTable((on) => !on)}>
            <Icon spec={codicon('table')} />
          </button>
        ) : null}
        {chart && !asTable
          ? (['png', 'png-light', 'svg'] as const).map((kind) => (
            <button key={kind} type="button" className="icon-btn" title={t(`dashboard.export.${kind}`)} aria-label={t(`dashboard.export.${kind}`)} onClick={() => downloadImage(name, chart, kind)}>
              <Icon spec={codicon(kind === 'svg' ? 'symbol-misc' : kind === 'png' ? 'device-camera' : 'color-mode')} />
            </button>
          ))
          : null}
        {csv ? (
          <button type="button" className="icon-btn" title={t('dashboard.exportCsv')} aria-label={t('dashboard.exportCsv')} disabled={!query?.data} onClick={() => downloadCsv(name, csv())}>
            <Icon spec={codicon('export')} />
          </button>
        ) : null}
      </div>
      <div className="db-view-body">
        <TableMode.Provider value={{ on: asTable, rows: csv }}>
          {empty ? <div className="empty">{empty}</div> : failed ? <ProblemState error={query.error} /> : query?.isLoading ? <div className="empty">{t('common.loading')}</div> : children}
        </TableMode.Provider>
      </div>
    </div>
  )
}

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

const FEATURE_LIST_BODY = { max_cells: 1 }

/** Full feature names of the run with their class */
export function useFeatureNames(runId: string): { name: string; cls: string }[] {
  const pid = usePid()
  const q = useDashboardView(pid, runId, 'missing-matrix', FEATURE_LIST_BODY)
  return useMemo(() => (q.data?.features ?? []).map((f) => ({ name: f.feature, cls: f.feature_class })), [q.data])
}

const DEFAULT_FEATURE = 'original_firstorder_Mean'

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

/** Point style for the linked selection: selected points stand out, others dim */
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

/** Open the item in a case tab */
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
    // Keep the item's current `seg` status and flag it for the queue; the event carries no seg_id,
    // so it is about `default_seg`
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
 *  `list` (label + all rows): the case tab follows that list on Alt+↓. */
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

/** Unit of analysis follows a single-label filter; otherwise the server default */
export function unitFor(labels: number[] | null | undefined): UnitSpec {
  return { aggregate: 'first', ...(labels?.length === 1 ? { label: labels[0] } : {}) }
}
