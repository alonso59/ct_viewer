// Per-run dashboard state shared by the views, the filter bar and the Analysis panel (DB-02/04/07/09).
// UI state only (Zustand); server data stays in TanStack Query.
import { create } from 'zustand'

import type { ColorBy, DashboardView, GlobalFilters } from '../../api'

/** A request to show one view with params (DB-09: result rows and recommendations open views) */
export interface FocusRequest {
  view: DashboardView
  params: Record<string, unknown>
  /** Increments on every request so the same view can be focused twice */
  nonce: number
}

export interface RunDashboard {
  /** DB-02 global filters, sent as `filters` in every API-38/39 body */
  filters: GlobalFilters
  /** DB-07 colour/split for the views that take one */
  colorBy: ColorBy | null
  /** DB-04 linked selection: item ids highlighted in every view */
  selection: string[]
  focus: FocusRequest | null
  /** Variables shown in the filter bar; only those with values are in `filters.var` */
  filterVars: string[]
}

const EMPTY: RunDashboard = { filters: {}, colorBy: { kind: 'phase' }, selection: [], focus: null, filterVars: [] }

interface DashboardStore {
  runs: Record<string, RunDashboard>
  patch: (runId: string, p: Partial<Omit<RunDashboard, 'focus'>>) => void
  setFilters: (runId: string, f: GlobalFilters) => void
  select: (runId: string, itemIds: string[]) => void
  focusView: (runId: string, view: DashboardView, params?: Record<string, unknown>) => void
}

export const useDashboardStore = create<DashboardStore>()((set) => {
  const update = (runId: string, fn: (r: RunDashboard) => Partial<RunDashboard>) =>
    set((s) => {
      const cur = s.runs[runId] ?? EMPTY
      return { runs: { ...s.runs, [runId]: { ...cur, ...fn(cur) } } }
    })
  return {
    runs: {},
    patch: (runId, p) => update(runId, () => p),
    setFilters: (runId, filters) => update(runId, () => ({ filters })),
    select: (runId, selection) => update(runId, () => ({ selection })),
    focusView: (runId, view, params = {}) => update(runId, (r) => ({ focus: { view, params, nonce: (r.focus?.nonce ?? 0) + 1 } })),
  }
})

/** State of one run's dashboard (defaults until something is set) */
export const useRunDashboard = (runId: string): RunDashboard => useDashboardStore((s) => s.runs[runId] ?? EMPTY)
