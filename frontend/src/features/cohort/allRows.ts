import { api, type CohortCaseRow, type CohortSort } from '../../api'
import type { CohortFilters } from './store'

const PAGE = 500

/** Every case the filters keep, in the grid's order (the API pages by 500) */
export async function allRows(pid: string, columns: string[], filters: CohortFilters, sort: CohortSort | null): Promise<CohortCaseRow[]> {
  const rows: CohortCaseRow[] = []
  for (let offset = 0; ; offset += PAGE) {
    const page = await api.cohortRows(pid, {
      columns,
      filters: filters.vars,
      ...(filters.q ? { q: filters.q } : {}),
      ...(filters.phase ? { phase: filters.phase } : {}),
      sort,
      offset,
      limit: PAGE,
    })
    const got = page.rows ?? []
    rows.push(...got)
    if (got.length < PAGE) return rows
  }
}
