import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useCohortRows, useVariables, type CohortRowsRequest, type CohortSort, type Variable } from '../../api'
import { ProblemCard } from '../../lib'
import { useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { Icon, codicon } from '../../theme'
import { CellMenu } from './CellMenu'
import { FilterBar } from './FilterBar'
import { Grid } from './Grid'
import { BalancePanel, ComparePanel, SummaryPanel, TagsPanel, TimelinePanel } from './Panels'
import { ExportButton } from './ExportButton'
import { useCohort, variablesOf, type GroupSelection } from './store'
import './cohort.css'

const PAGE = 100

/** Grid columns: the open group's visible, non-constant variables, plus the pinned ones */
const columnsFor = (all: Variable[], group: GroupSelection | null, pinned: string[]): Variable[] => {
  const inGroup = variablesOf(all, group).filter((v) => v.type !== 'constant')
  const names = new Set(inGroup.map((v) => v.name))
  return [...inGroup, ...all.filter((v) => pinned.includes(v.name) && !names.has(v.name) && v.type !== 'constant')]
}

/** The grid and its pager; remounted (via key) on a new group or filter, starting on page one */
function GridSection({ columns, sort, onSort }: {
  columns: Variable[]
  sort: CohortSort | null
  onSort: (column: string) => void
}) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const filters = useCohort((s) => s.filters)
  const [page, setPage] = useState(0)
  const req = useMemo<CohortRowsRequest | null>(() => ({
    columns: columns.map((v) => v.name),
    filters: filters.vars,
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.phase ? { phase: filters.phase } : {}),
    sort,
    offset: page * PAGE,
    limit: PAGE,
  }) satisfies CohortRowsRequest, [columns, sort, page, filters])
  const rows = useCohortRows(pid, req)
  const pages = Math.max(1, Math.ceil((rows.data?.n_cases ?? 0) / PAGE))
  return (
    <>
      {rows.isError && !rows.data ? (
        <ProblemCard error={rows.error} onRetry={() => void rows.refetch()} />
      ) : (
        <Grid columns={columns} rows={rows.data?.rows ?? []} sort={sort} onSort={onSort} />
      )}
      <div className="cohort-pager">
        <ExportButton columns={columns} />
        <button type="button" className="btn btn-sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
          <Icon spec={codicon('chevron-left')} />
          {t('cohort.grid.previous')}
        </button>
        <span className="muted">{t('cohort.grid.page', { page: page + 1, pages })}</span>
        <button type="button" className="btn btn-sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
          {t('cohort.grid.next')}
          <Icon spec={codicon('chevron-right')} />
        </button>
      </div>
    </>
  )
}

export function CohortEditor() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const vars = useVariables(pid)
  // The grid's fields are chosen in the Cohort navigator, so opening the grid shows it
  useEffect(() => { useLayout.getState().set({ activeView: 'cohort', sidebarVisible: true }) }, [])
  const group = useCohort((s) => s.group)
  const pinned = useCohort((s) => s.pinned)
  const filters = useCohort((s) => s.filters)
  const compareCase = useCohort((s) => s.compareCase)
  const summaryColumn = useCohort((s) => s.summaryColumn)
  const tagsItem = useCohort((s) => s.tagsItem)
  const balance = useCohort((s) => s.balance)
  const timelineCase = useCohort((s) => s.timelineCase)
  const sort = useCohort((s) => s.sort)
  const setSort = useCohort((s) => s.setSort)
  const columns = useMemo(() => columnsFor(vars.data ?? [], group, pinned), [vars.data, group, pinned])
  // The identity a grid remounts on: group and filters (a re-sort keeps the open page)
  const identity = useMemo(() => JSON.stringify({ columns: columns.map((v) => v.name), filters }), [columns, filters])
  if (vars.isError) return <ProblemCard error={vars.error} onRetry={() => { void vars.refetch() }} />
  return (
    <div className="cohort-editor">
      <FilterBar />
      <CellMenu />
      {summaryColumn ? <SummaryPanel column={summaryColumn} /> : null}
      {compareCase ? <ComparePanel caseId={compareCase} /> : null}
      {tagsItem ? <TagsPanel itemId={tagsItem} /> : null}
      {balance ? <BalancePanel a={balance.a} b={balance.b} /> : null}
      {timelineCase ? <TimelinePanel caseId={timelineCase} /> : null}
      {columns.length === 0 ? <div className="muted cohort-hint">{t('cohort.grid.noColumns')}</div> : null}
      <GridSection
        key={identity}
        columns={columns}
        sort={sort}
        onSort={(column) => setSort(sort?.column === column ? { column, desc: !sort.desc } : { column, desc: false })}
      />
    </div>
  )
}
