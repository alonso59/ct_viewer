// Per-run dashboard UI state shared by the views, the filter bar and the Analysis panel; server data stays in TanStack Query.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { ColorBy, DashboardView, GlobalFilters } from '../../api'

/** A request to show one view with params */
interface FocusRequest {
  view: DashboardView
  params: Record<string, unknown>
  /** Increments on every request so the same view can be focused twice */
  nonce: number
}

export interface RunDashboard {
  /** Global filters, sent as `filters` in every view and analysis request body */
  filters: GlobalFilters
  /** Colour/split for the views that take one */
  colorBy: ColorBy | null
  /** Linked selection: item ids highlighted in every view */
  selection: string[]
  focus: FocusRequest | null
  /** Variables shown in the filter bar; only those with values are in `filters.var` */
  filterVars: string[]
}

const EMPTY: RunDashboard = { filters: {}, colorBy: { kind: 'phase' }, selection: [], focus: null, filterVars: [] }

interface DashboardStore {
  runs: Record<string, RunDashboard>
  patch: (tableId: string, p: Partial<Omit<RunDashboard, 'focus'>>) => void
  setFilters: (tableId: string, f: GlobalFilters) => void
  select: (tableId: string, itemIds: string[]) => void
  focusView: (tableId: string, view: DashboardView, params?: Record<string, unknown>) => void
}

/** What survives a reload: a run's filters and colouring, not its selection */
type Kept = Pick<RunDashboard, 'filters' | 'colorBy' | 'filterVars'>

export const useDashboardStore = create<DashboardStore>()(persist((set) => {
  const update = (tableId: string, fn: (r: RunDashboard) => Partial<RunDashboard>) =>
    set((s) => {
      const cur = s.runs[tableId] ?? EMPTY
      return { runs: { ...s.runs, [tableId]: { ...cur, ...fn(cur) } } }
    })
  return {
    runs: {},
    patch: (tableId, p) => update(tableId, () => p),
    setFilters: (tableId, filters) => update(tableId, () => ({ filters })),
    select: (tableId, selection) => update(tableId, () => ({ selection })),
    focusView: (tableId, view, params = {}) => update(tableId, (r) => ({ focus: { view, params, nonce: (r.focus?.nonce ?? 0) + 1 } })),
  }
}, {
  name: 'rw.dashboard',
  partialize: (s) => ({ runs: Object.fromEntries(Object.entries(s.runs).map(([id, r]): [string, Kept] => [id, { filters: r.filters, colorBy: r.colorBy, filterVars: r.filterVars }])) }),
  merge: (saved, current) => ({
    ...current,
    runs: Object.fromEntries(Object.entries((saved as { runs?: Record<string, Kept> } | undefined)?.runs ?? {}).map(([id, r]) => [id, { ...EMPTY, ...r }])),
  }),
}))

/** State of one run's dashboard (defaults until something is set) */
export const useTableDashboard = (tableId: string): RunDashboard => useDashboardStore((s) => s.runs[tableId] ?? EMPTY)
