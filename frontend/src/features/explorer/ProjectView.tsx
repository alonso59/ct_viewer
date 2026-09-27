// Project view (QuPath Project tab): case list with axial thumbnails, badges, expand to items (UI-08).
// Study variables drive the row columns and colour (VAR-10); nothing here knows a field name.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import {
  useCase,
  useCases,
  useImportHistory,
  useProject,
  useThumbItemId,
  useVariables,
  type CaseSummary,
  type ItemRecord,
  type LabelDef,
  type Variable,
} from '../../api'
import { PhaseChip, rollupTitle, SliceThumb, StatusIcon } from '../../lib'
import { registry, useWorkbench } from '../../shell'
import { useSettings, useViewerSync } from '../../state'
import { Icon, codicon, tokenPx } from '../../theme'
import { PhaseButtons } from '../phase'
import { itemLabel } from './itemLabel'
import { openFromExplorer } from './navigate'
import { activeFilterCount, useExplorer, useExplorerPrefs, usePrefs } from './store'
import { colorable, columnable, formatValue, levelColor } from './vars'
import './explorer.css'

function CaseThumb({ pid, c, labels }: { pid: string; c: CaseSummary; labels?: LabelDef[] }) {
  const itemId = useThumbItemId(pid, c)
  return <SliceThumb pid={pid} itemId={itemId} labels={labels} size="var(--thumb-row)" />
}

/** `name value` chips for the chosen variable columns */
function VarColumns({ c, columns }: { c: CaseSummary; columns: Variable[] }) {
  return (
    <>
      {columns.map((v) => (
        <span key={v.name} className="var-chip" title={v.name}>
          <span className="muted">{v.name}</span>
          <span className="num">{formatValue(v, c.variables[v.name] ?? null)}</span>
        </span>
      ))}
    </>
  )
}

type Row = { kind: 'case'; c: CaseSummary } | { kind: 'item'; item: ItemRecord; caseId: string } | { kind: 'loading'; caseId: string }

function ExpandedItems({ caseId, onItems }: { caseId: string; onItems: (cid: string, items: ItemRecord[]) => void }) {
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data } = useCase(pid, caseId)
  useEffect(() => {
    if (data) onItems(caseId, data.items)
  }, [data, caseId, onItems])
  return null
}

export function ProjectView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { filter, setFilter, expanded, toggle, setOrder } = useExplorer()
  const density = useSettings((s) => s.rowDensity)
  const activeItemId = useViewerSync((s) => s.activeItemId)
  const activeCaseId = useViewerSync((s) => s.activeCaseId)
  const project = useProject(pid)
  const index = useImportHistory(pid).data?.index
  const cases = useCases(pid, filter)
  const variables = useVariables(pid).data ?? []
  const prefs = usePrefs(pid)
  const byName = new Map(variables.map((v) => [v.name, v]))
  const columns = prefs.columns.map((n) => byName.get(n)).filter((v): v is Variable => v !== undefined && v.visible)
  const colorVar = prefs.colorBy ? byName.get(prefs.colorBy) : undefined
  const [itemsByCase, setItemsByCase] = useState<Record<string, ItemRecord[]>>({})
  const [cursor, setCursor] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  const onItems = useMemo(
    () => (cid: string, items: ItemRecord[]) => setItemsByCase((m) => (m[cid] === items ? m : { ...m, [cid]: items })),
    [],
  )

  useEffect(() => {
    if (cases.data) setOrder(cases.data.map((c) => c.case_id))
  }, [cases.data, setOrder])

  const itemIds = filter.itemIds
  const rows: Row[] = useMemo(() => {
    const out: Row[] = []
    // DB-04 item filter: an expanded case lists only the chosen items
    const only = itemIds ? new Set(itemIds) : null
    for (const c of cases.data ?? []) {
      out.push({ kind: 'case', c })
      if (expanded[c.case_id]) {
        const items = itemsByCase[c.case_id]
        if (!items) out.push({ kind: 'loading', caseId: c.case_id })
        else for (const item of items) if (!only || only.has(item.item_id)) out.push({ kind: 'item', item, caseId: c.case_id })
      }
    }
    return out
  }, [cases.data, expanded, itemsByCase, itemIds])

  // UI-08 / UI-27: row heights come from the tokens of the current interface size
  const uiSize = useSettings((s) => s.uiSize)
  // (read on every render; the fallback, for a document without the tokens, follows the size too)
  const rowH = tokenPx('--h-row-compact', uiSize === 'compact' ? 22 : 24)
  const thumbH = tokenPx('--h-row-thumb', uiSize === 'compact' ? 56 : 60)
  const caseH = density === 'thumbnails' ? thumbH : rowH
  // TanStack Virtual is not React-compiler compatible yet; the compiler skips this component, which is fine here
  // eslint-disable-next-line react-hooks/incompatible-library
  const virt = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => (rows[i]?.kind === 'case' ? caseH : rowH),
    overscan: 8,
  })
  useEffect(() => virt.measure(), [caseH, rowH, virt])

  // AUD-A1-03: follow the active case (and item, when its case is expanded), like VS Code's
  // "reveal active file": the keyboard cursor moves there and the row scrolls into view
  const revealed = useRef('')
  useEffect(() => {
    if (!activeCaseId) return
    const key = `${activeCaseId}|${activeItemId ?? ''}`
    if (revealed.current === key) return
    const item = activeItemId ? rows.findIndex((r) => r.kind === 'item' && r.item.item_id === activeItemId) : -1
    const i = item >= 0 ? item : rows.findIndex((r) => r.kind === 'case' && r.c.case_id === activeCaseId)
    if (i < 0) return
    revealed.current = key
    setCursor(i)
    virt.scrollToIndex(i, { align: 'auto' })
  }, [activeCaseId, activeItemId, rows, virt])

  const activate = (r: Row | undefined, preview = true) => {
    if (!r) return
    if (r.kind === 'case') openFromExplorer(r.c.case_id, null, preview)
    if (r.kind === 'item') openFromExplorer(r.caseId, r.item.item_id, preview)
  }

  const onKey = (e: KeyboardEvent) => {
    const r = rows[cursor]
    const move = (i: number) => {
      const n = Math.max(0, Math.min(rows.length - 1, i))
      setCursor(n)
      virt.scrollToIndex(n)
    }
    if (e.key === 'ArrowDown') move(cursor + 1)
    else if (e.key === 'ArrowUp') move(cursor - 1)
    else if (e.key === 'ArrowRight' && r?.kind === 'case') toggle(r.c.case_id, true)
    else if (e.key === 'ArrowLeft' && r?.kind === 'case') toggle(r.c.case_id, false)
    else if (e.key === 'Enter') activate(r, false)
    else if (e.key === ' ') activate(r, true)
    else return
    e.preventDefault()
  }

  if (project.isError || cases.isError) {
    const err = (cases.error ?? project.error) as { title?: string; detail?: string } | null
    return (
      <div className="error-card" role="alert">
        <strong>{err?.title ?? t('common.error')}</strong>
        <div className="muted">{err?.detail}</div>
      </div>
    )
  }

  return (
    <div className="fill">
      <div className="pv-filter">
        <input
          className="input input-sm"
          placeholder={t('explorer.filterPlaceholder')}
          value={filter.q ?? ''}
          onChange={(e) => setFilter({ q: e.target.value })}
          aria-label={t('explorer.filterPlaceholder')}
        />
        <Icon spec={codicon('filter')} />
      </div>
      {colorVar ? <ColorLegend v={colorVar} /> : null}
      {itemIds ? <ItemFilterChip ids={itemIds} /> : null}
      {activeFilterCount(filter) > 0 ? (
        <div className="muted row pv-active-filters">
          {t('explorer.filtersActive', { count: activeFilterCount(filter) })}
          <button type="button" className="link" onClick={() => useExplorer.getState().clearFilter()}>
            {t('explorer.clearFilters')}
          </button>
        </div>
      ) : null}
      <div
        ref={scrollRef}
        role="tree"
        aria-label={t('view.project')}
        tabIndex={0}
        onKeyDown={onKey}
        className="pv-tree"
      >
        {cases.isLoading ? <div className="empty">{t('common.loading')}</div> : null}
        {cases.data?.length === 0 ? (
          <div className="empty">
            {t(index?.state === 'running' ? 'explorer.indexing' : index?.state === 'ready' || activeFilterCount(filter) || filter.q ? 'explorer.noCases' : 'explorer.emptyProject')}
          </div>
        ) : null}
        <div style={{ height: virt.getTotalSize(), position: 'relative' }}>
          {virt.getVirtualItems().map((v) => {
            const r = rows[v.index]
            if (!r) return null
            const style = { position: 'absolute' as const, top: 0, left: 0, right: 0, height: v.size, transform: `translateY(${v.start}px)` }
            const focused = v.index === cursor
            if (r.kind === 'loading')
              return (
                <div key={`l-${r.caseId}`} style={style} className="muted pv-loading">
                  {t('common.loading')}
                </div>
              )
            if (r.kind === 'item') {
              const it = r.item
              const excluded = it.status === 'excluded_upstream'
              // A div, not a button: the row holds the PHS-01 phase buttons (the tree handles keys)
              return (
                <div
                  key={it.item_id}
                  role="treeitem"
                  aria-level={2}
                  aria-selected={activeItemId === it.item_id}
                  aria-disabled={excluded || undefined}
                  className="list-row pv-item"
                  data-focused={focused}
                  data-density={density}
                  data-excluded={excluded || undefined}
                  style={style}
                  onClick={() => { if (!excluded) { setCursor(v.index); activate(r) } }}
                  onDoubleClick={() => !excluded && activate(r, false)}
                >
                  <span className="phase-row-static"><PhaseChip phase={it.phase.canonical} /></span>
                  <span className="item-label">{itemLabel(it, t)}</span>
                  {it.warning_codes.length ? (
                    <span className="pv-warn pv-end" title={it.warning_codes.join(', ')}>
                      <Icon spec={codicon('warning')} />
                    </span>
                  ) : null}
                  {it.status === 'missing' ? <span className="badge" data-tone="error">{t('explorer.missing')}</span> : null}
                  {excluded || registry.readOnly ? null : <PhaseButtons pid={pid} scan={it} className="phase-row-actions" />}
                </div>
              )
            }
            const c = r.c
            const open = expanded[c.case_id] === true
            const swatch = colorVar ? levelColor(colorVar, c.variables[colorVar.name] ?? null) : null
            return (
              <div
                key={c.case_id}
                role="treeitem"
                aria-level={1}
                aria-expanded={open}
                aria-selected={activeCaseId === c.case_id}
                className="list-row pv-case"
                data-focused={focused}
                data-excluded={c.excluded || undefined}
                data-swatch={swatch ? true : undefined}
                // Colour-by variable: a left stripe in the categorical palette
                style={swatch ? { ...style, '--swatch': swatch } as CSSProperties : style}
                data-color={swatch ? String(c.variables[colorVar?.name ?? '']) : undefined}
                onClick={() => { setCursor(v.index); activate(r) }}
                onDoubleClick={() => activate(r, false)}
              >
                <button
                  type="button"
                  className="icon-btn pv-twisty"
                  aria-label={t(open ? 'explorer.collapse' : 'explorer.expand')}
                  onClick={(e) => { e.stopPropagation(); toggle(c.case_id) }}
                >
                  <Icon spec={codicon(open ? 'chevron-down' : 'chevron-right')} />
                </button>
                {density === 'thumbnails' ? <CaseThumb pid={pid} c={c} labels={project.data?.label_map} /> : null}
                <span className="pv-case-body">
                  <span className="pv-case-line">
                    <span className="mono panel-size">{c.case_id}</span>
                    {density === 'compact' ? <VarColumns c={c} columns={columns} /> : null}
                    <span className="row-1 pv-end">
                      {c.n_warnings ? (
                        <span className="pv-warn small" title={t('explorer.warnings', { count: c.n_warnings })}>
                          <Icon spec={codicon('warning')} />
                          {c.n_warnings}
                        </span>
                      ) : null}
                      <span title={rollupTitle(t, c)}>
                        <StatusIcon status={c.curation_status} />
                      </span>
                    </span>
                  </span>
                  {density === 'thumbnails' ? (
                    <span className="muted pv-case-meta">
                      <VarColumns c={c} columns={columns} />
                      {c.phases.map((p) => (
                        <PhaseChip key={p} phase={p} />
                      ))}
                      {c.has_voi_L || c.has_voi_R ? <span className="badge">{t('explorer.voi')}</span> : null}
                      {c.excluded ? <span className="badge">{t('explorer.excluded')}</span> : null}
                    </span>
                  ) : null}
                </span>
              </div>
            )
          })}
        </div>
        {Object.keys(expanded)
          .filter((k) => expanded[k])
          .map((cid) => (
            <ExpandedItems key={cid} caseId={cid} onItems={onItems} />
          ))}
      </div>
      <div className="muted pv-footer">
        {t('explorer.caseCount', { count: cases.data?.length ?? 0 })}
      </div>
    </div>
  )
}

/** DB-04: the Explorer shows only the items sent from a dashboard selection; clearable */
export function ItemFilterChip({ ids }: { ids: string[] }) {
  const { t } = useTranslation()
  return (
    <div className="pv-chip-row">
      <span className="badge item-filter-chip" data-tone="accent" title={ids.join('\n')}>
        <Icon spec={codicon('filter')} />
        {t('explorer.itemFilter', { count: ids.length })}
        <button
          type="button"
          className="icon-btn pv-chip-close"
          aria-label={t('explorer.clearItemFilter')}
          title={t('explorer.clearItemFilter')}
          onClick={() => useExplorer.getState().setItemIds(null)}
        >
          <Icon spec={codicon('close')} />
        </button>
      </span>
    </div>
  )
}

/** Header menu: which case-level variables show as columns, and which one colours the rows */
function ColumnsMenu() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const vars = useVariables(pid).data ?? []
  const prefs = usePrefs(pid)
  const { toggleColumn, setColorBy } = useExplorerPrefs.getState()
  const cols = columnable(vars)
  const colors = colorable(vars)
  return (
    <Menu.Root>
      <Menu.Trigger className="icon-btn" aria-label={t('explorer.columns')} title={t('explorer.columns')}>
        <Icon spec={codicon('symbol-variable')} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" align="end" sideOffset={2}>
          <Menu.Label className="menu-label">{t('explorer.showColumns')}</Menu.Label>
          {cols.length === 0 ? <Menu.Item className="menu-item" disabled>{t('explorer.noVariables')}</Menu.Item> : null}
          {cols.map((v) => (
            <Menu.CheckboxItem key={v.name} className="menu-item" checked={prefs.columns.includes(v.name)} onSelect={(e) => e.preventDefault()} onCheckedChange={() => toggleColumn(pid, v.name)}>
              <Icon spec={codicon(prefs.columns.includes(v.name) ? 'check' : 'blank')} />
              {v.name}
            </Menu.CheckboxItem>
          ))}
          <Menu.Separator className="menu-sep" />
          <Menu.Label className="menu-label">{t('explorer.colorBy')}</Menu.Label>
          <Menu.RadioGroup value={prefs.colorBy ?? ''} onValueChange={(v) => setColorBy(pid, v || null)}>
            <Menu.RadioItem value="" className="menu-item">
              <Icon spec={codicon(prefs.colorBy ? 'blank' : 'check')} />
              {t('common.none')}
            </Menu.RadioItem>
            {colors.map((v) => (
              <Menu.RadioItem key={v.name} value={v.name} className="menu-item">
                <Icon spec={codicon(prefs.colorBy === v.name ? 'check' : 'blank')} />
                {v.name}
              </Menu.RadioItem>
            ))}
          </Menu.RadioGroup>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}

/** Legend for the colour-by variable, under the filter box */
function ColorLegend({ v }: { v: Variable }) {
  const levels = [...(v.profile.levels ?? [])].sort((a, b) => a.value.localeCompare(b.value, 'en', { numeric: true }))
  return (
    <div className="color-legend" aria-label={v.name}>
      <span className="muted">{v.name}</span>
      {levels.map((l) => (
        <span key={l.value} className="color-legend-item">
          <span className="dot" style={{ background: levelColor(v, l.value) ?? undefined }} />
          {l.value}
        </span>
      ))}
    </div>
  )
}

export function ProjectViewActions() {
  const { t } = useTranslation()
  const density = useSettings((s) => s.rowDensity)
  const set = useSettings((s) => s.set)
  const { expanded } = useExplorer()
  return (
    <>
      <ColumnsMenu />
      <button
        type="button"
        className="icon-btn"
        aria-label={t(density === 'thumbnails' ? 'explorer.compactRows' : 'explorer.thumbnailRows')}
        title={t(density === 'thumbnails' ? 'explorer.compactRows' : 'explorer.thumbnailRows')}
        onClick={() => set({ rowDensity: density === 'thumbnails' ? 'compact' : 'thumbnails' })}
      >
        <Icon spec={codicon(density === 'thumbnails' ? 'list-flat' : 'list-tree')} />
      </button>
      <button
        type="button"
        className="icon-btn"
        aria-label={t('explorer.collapseAll')}
        title={t('explorer.collapseAll')}
        disabled={!Object.values(expanded).some(Boolean)}
        onClick={() => useExplorer.setState({ expanded: {} })}
      >
        <Icon spec={codicon('collapse-all')} />
      </button>
    </>
  )
}
