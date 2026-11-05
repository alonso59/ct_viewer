import { useEffect, useMemo, useRef, type MouseEvent } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useTranslation } from 'react-i18next'

import { type CohortCaseRow, type CohortScanRow, type CohortSort, type Variable } from '../../api'
import { fmtValue, useRowKeys } from '../../lib'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { type CellTarget, useCellMenu } from './CellMenu'
import { ClinicalCell } from './ClinicalCell'
import { useClinicalColumns } from './clinical'
import { useCohort } from './store'

type Flat =
  | { key: string; kind: 'case'; c: CohortCaseRow }
  | { key: string; kind: 'scan'; c: CohortCaseRow; s: CohortScanRow }

/** "No value" placeholder; a constant, since JSX may not hold string children */
const DASH = '—'

function ValueCell({ v }: { v: number | string | null | undefined }) {
  if (v === null || v === undefined) return <span className="muted">{DASH}</span>
  return <span className={typeof v === 'number' ? 'num' : undefined}>{typeof v === 'number' ? fmtValue(v) : v}</span>
}

/** A case cell: the common value, a differs marker with its count in words, or a dash */
function CaseCell({ c, name }: { c: CohortCaseRow; name: string }) {
  const { t } = useTranslation()
  const v = c.values?.[name]
  if ((v === null || v === undefined) && c.differs?.includes(name)) {
    const n = new Set((c.scans ?? []).map((s) => s.values?.[name]).filter((x) => x !== null && x !== undefined)).size
    return (
      <span className="cohort-differs" title={t('cohort.grid.differs', { n })}>
        <Icon spec={codicon('diff')} />
        {t('cohort.grid.differs', { n })}
      </span>
    )
  }
  return <ValueCell v={v} />
}

function SortHeader({ label, column, sort, onSort }: { label: string; column: string; sort: CohortSort | null; onSort: (column: string) => void }) {
  const active = sort && sort.column === column ? sort : null
  return (
    <button type="button" role="columnheader" className="cohort-sort" aria-sort={active ? (active.desc ? 'descending' : 'ascending') : 'none'} title={label} onClick={() => onSort(column)}>
      <span className="mono">{label}</span>
      {active ? <Icon spec={codicon(active.desc ? 'arrow-down' : 'arrow-up')} /> : null}
    </button>
  )
}

/** The cohort grid: one row per case, its scans when expanded, the open group's columns */
export function Grid({ columns, rows, sort, onSort }: {
  columns: Variable[]
  rows: CohortCaseRow[]
  sort: CohortSort | null
  onSort: (column: string) => void
}) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const clinical = useClinicalColumns(pid)
  const expanded = useCohort((s) => s.expanded)
  const toggle = useCohort((s) => s.toggleExpanded)
  const focusCase = useCohort((s) => s.focusCase)
  const flat = useMemo<Flat[]>(
    () =>
      rows.flatMap((c) => {
        const out: Flat[] = [{ key: c.case_id, kind: 'case', c }]
        if (expanded[c.case_id]) for (const s of c.scans ?? []) out.push({ key: `${c.case_id}/${s.scan_idx}`, kind: 'scan', c, s })
        return out
      }),
    [rows, expanded],
  )
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // TanStack Virtual is not React-compiler compatible yet; the compiler skips this component, which is fine here
  // eslint-disable-next-line react-hooks/incompatible-library
  const virt = useVirtualizer({
    count: flat.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 24,
    overscan: 8,
  })
  useEffect(() => {
    virt.measure()
  }, [flat.length, virt])
  // An entry point (the Explorer's case menu, the Image section) asks for one case: reveal it
  useEffect(() => {
    if (!focusCase) return
    const i = flat.findIndex((f) => f.kind === 'case' && f.c.case_id === focusCase)
    if (i < 0) return
    virt.scrollToIndex(i, { align: 'center' })
  }, [focusCase, flat, virt])
  const keys = useRowKeys(flat.map((f) => f.key))
  const openMenu = useCellMenu((s) => s.open)
  // A variable cell keeps its column and value; the rest of the row opens without them
  const menu = (e: MouseEvent<HTMLElement>, target: Omit<CellTarget, 'x' | 'y'>) => {
    e.preventDefault()
    e.stopPropagation()
    openMenu({ ...target, x: e.clientX, y: e.clientY })
  }
  const template = `20px 180px 72px 80px${columns.length ? ` repeat(${columns.length}, minmax(90px, 1fr))` : ''}`
  return (
    <div className="cohort-grid-wrap">
      <div className="cohort-grid-head" role="row" style={{ gridTemplateColumns: template }}>
        <span />
        <SortHeader label={t('cohort.grid.case')} column="case_id" sort={sort} onSort={onSort} />
        <span />
        <span className="cohort-head-sub">{t('cohort.grid.modality')}</span>
        {columns.map((v) => <SortHeader key={v.name} label={v.name} column={v.name} sort={sort} onSort={onSort} />)}
      </div>
      <div className="cohort-grid" ref={scrollRef}>
        <div style={{ height: virt.getTotalSize(), position: 'relative' }}>
          {virt.getVirtualItems().map((item) => {
            const f = flat[item.index]
            if (!f) return null
            const open = f.kind === 'case' ? !!expanded[f.c.case_id] : false
            return (
              <div
                key={item.key}
                {...keys(f.key)}
                className={f.kind === 'case' ? 'cohort-row cohort-row-case' : 'cohort-row cohort-row-scan'}
                data-focused={f.kind === 'case' && f.c.case_id === focusCase ? true : undefined}
                style={{ position: 'absolute', top: 0, left: 0, right: 0, height: item.size, transform: `translateY(${item.start}px)`, display: 'grid', gridTemplateColumns: template, alignItems: 'center' }}
                aria-expanded={f.kind === 'case' ? open : undefined}
                onClick={f.kind === 'case' ? () => toggle(f.c.case_id) : undefined}
                onContextMenu={(e) =>
                  menu(e, {
                    caseId: f.c.case_id,
                    scanIdx: f.kind === 'case' ? null : f.s.scan_idx,
                    itemId: f.kind === 'case' ? (f.c.scans?.[0]?.item_id ?? null) : f.s.item_id,
                    column: null,
                    value: null,
                    label: f.kind === 'case' ? f.c.case_id : f.s.scan_idx,
                  })
                }
              >
                {f.kind === 'case' ? (
                  <>
                    <span><Icon spec={codicon(open ? 'chevron-down' : 'chevron-right')} /></span>
                    <span className="cohort-cell-id" title={f.c.case_id}>{f.c.case_id}</span>
                    <span className="muted">{t('cohort.grid.scans', { n: f.c.scans?.length ?? 0 })}</span>
                    <span />
                    {columns.map((v) => (
                      <span
                        key={v.name}
                        className="cohort-cell"
                        onContextMenu={(e) =>
                          menu(e, {
                            caseId: f.c.case_id,
                            scanIdx: null,
                            itemId: f.c.scans?.[0]?.item_id ?? null,
                            column: v.name,
                            value: f.c.values?.[v.name] ?? null,
                            label: v.name,
                          })
                        }
                      >
                        <ClinicalCell column={v} info={clinical.get(v.name)} caseId={f.c.case_id} scanIdx={null} value={f.c.values?.[v.name]}>
                          <CaseCell c={f.c} name={v.name} />
                        </ClinicalCell>
                      </span>
                    ))}
                  </>
                ) : (
                  <>
                    <span />
                    <span className="cohort-cell-id muted">{f.s.scan_idx}</span>
                    <span>{f.s.phase}</span>
                    <span className="muted">{f.s.modality ?? '—'}</span>
                    {columns.map((v) => (
                      <span
                        key={v.name}
                        className="cohort-cell"
                        onContextMenu={(e) =>
                          menu(e, { caseId: f.c.case_id, scanIdx: f.s.scan_idx, itemId: f.s.item_id, column: v.name, value: f.s.values?.[v.name] ?? null, label: v.name })
                        }
                      >
                        <ClinicalCell column={v} info={clinical.get(v.name)} caseId={f.c.case_id} scanIdx={f.s.scan_idx} value={f.s.values?.[v.name]}>
                          <ValueCell v={f.s.values?.[v.name]} />
                        </ClinicalCell>
                      </span>
                    ))}
                  </>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
