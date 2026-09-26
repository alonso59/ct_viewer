// Project view (QuPath Project tab): case list with axial thumbnails, badges, expand to items (UI-08).
// Study variables drive the row columns and colour (VAR-10); nothing here knows a field name.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
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
import { openEditor, registry, useWorkbench } from '../../shell'
import { useSettings, useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { PhaseButtons } from '../phase'
import { itemLabel } from './itemLabel'
import { activeFilterCount, useExplorer, useExplorerPrefs, usePrefs } from './store'
import { colorable, columnable, formatValue, levelColor } from './vars'
import './explorer.css'

function CaseThumb({ pid, c, labels }: { pid: string; c: CaseSummary; labels?: LabelDef[] }) {
  const itemId = useThumbItemId(pid, c)
  return <SliceThumb pid={pid} itemId={itemId} labels={labels} size={44} />
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

export function openItem(caseId: string, itemId: string | null, preview = true) {
  openEditor('case', { caseId, itemId }, { preview })
}

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

  const caseH = density === 'thumbnails' ? 56 : 22
  // TanStack Virtual is not React-compiler compatible yet; the compiler skips this component, which is fine here
  // eslint-disable-next-line react-hooks/incompatible-library
  const virt = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => (rows[i]?.kind === 'case' ? caseH : 22),
    overscan: 8,
  })
  useEffect(() => virt.measure(), [caseH, virt])

  const activate = (r: Row | undefined, preview = true) => {
    if (!r) return
    if (r.kind === 'case') openItem(r.c.case_id, null, preview)
    if (r.kind === 'item') openItem(r.caseId, r.item.item_id, preview)
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
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', gap: 4, padding: '0 8px 6px' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <input
            className="input input-sm"
            style={{ width: '100%', paddingLeft: 24 }}
            placeholder={t('explorer.filterPlaceholder')}
            value={filter.q ?? ''}
            onChange={(e) => setFilter({ q: e.target.value })}
            aria-label={t('explorer.filterPlaceholder')}
          />
          <span style={{ position: 'absolute', left: 6, top: 4, color: 'var(--fg-muted)' }}>
            <Icon spec={codicon('filter')} />
          </span>
        </div>
      </div>
      {colorVar ? <ColorLegend v={colorVar} /> : null}
      {itemIds ? <ItemFilterChip ids={itemIds} /> : null}
      {activeFilterCount(filter) > 0 ? (
        <div className="muted" style={{ padding: '0 12px 6px', fontSize: 'var(--fs-panel)', display: 'flex', gap: 6 }}>
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
        style={{ flex: 1, overflow: 'auto', outline: 'none' }}
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
                <div key={`l-${r.caseId}`} style={{ ...style, paddingLeft: 40 }} className="muted">
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
                  className="list-row"
                  data-focused={focused}
                  style={{ ...style, paddingLeft: density === 'thumbnails' ? 58 : 34, gap: 6, fontSize: 'var(--fs-panel)', boxShadow: focused ? 'inset 0 0 0 1px var(--focus)' : undefined, opacity: excluded ? 0.55 : undefined }}
                  onClick={() => { if (!excluded) { setCursor(v.index); activate(r) } }}
                  onDoubleClick={() => !excluded && activate(r, false)}
                >
                  <span className="phase-row-static"><PhaseChip phase={it.phase.canonical} /></span>
                  <span className="item-label">{itemLabel(it, t)}</span>
                  {it.warning_codes.length ? (
                    <span style={{ color: 'var(--warn)', display: 'inline-flex', marginLeft: 'auto' }} title={it.warning_codes.join(', ')}>
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
                className="list-row"
                style={{
                  ...style,
                  paddingLeft: 4,
                  gap: 6,
                  // Colour-by variable: a left stripe in the categorical palette
                  boxShadow: [focused ? 'inset 0 0 0 1px var(--focus)' : '', swatch ? `inset 3px 0 0 ${swatch}` : ''].filter(Boolean).join(', ') || undefined,
                  opacity: c.excluded ? 0.55 : 1,
                }}
                data-color={swatch ? String(c.variables[colorVar?.name ?? '']) : undefined}
                onClick={() => { setCursor(v.index); activate(r) }}
                onDoubleClick={() => activate(r, false)}
              >
                <button
                  type="button"
                  className="icon-btn"
                  style={{ width: 16, height: 16 }}
                  aria-label={t(open ? 'explorer.collapse' : 'explorer.expand')}
                  onClick={(e) => { e.stopPropagation(); toggle(c.case_id) }}
                >
                  <Icon spec={codicon(open ? 'chevron-down' : 'chevron-right')} />
                </button>
                {density === 'thumbnails' ? <CaseThumb pid={pid} c={c} labels={project.data?.label_map} /> : null}
                <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1, gap: 2 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span className="mono" style={{ fontSize: 'var(--fs-panel)' }}>{c.case_id}</span>
                    {density === 'compact' ? <VarColumns c={c} columns={columns} /> : null}
                    <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                      {c.n_warnings ? (
                        <span style={{ color: 'var(--warn)', display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 'var(--fs-badge)' }} title={t('explorer.warnings', { count: c.n_warnings })}>
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
                    <span className="muted" style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 'var(--fs-badge)', overflow: 'hidden', whiteSpace: 'nowrap' }}>
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
      <div className="muted" style={{ padding: '4px 12px', fontSize: 'var(--fs-badge)', borderTop: '1px solid var(--border-muted)' }}>
        {t('explorer.caseCount', { count: cases.data?.length ?? 0 })}
      </div>
    </div>
  )
}

/** DB-04: the Explorer shows only the items sent from a dashboard selection; clearable */
export function ItemFilterChip({ ids }: { ids: string[] }) {
  const { t } = useTranslation()
  return (
    <div style={{ padding: '0 8px 6px' }}>
      <span className="badge item-filter-chip" data-tone="accent" title={ids.join('\n')}>
        <Icon spec={codicon('filter')} />
        {t('explorer.itemFilter', { count: ids.length })}
        <button
          type="button"
          className="icon-btn"
          style={{ width: 14, height: 14 }}
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
