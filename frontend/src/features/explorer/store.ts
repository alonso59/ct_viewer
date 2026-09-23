import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { CaseFilter } from '../../api'

interface ExplorerState {
  filter: CaseFilter
  expanded: Record<string, boolean>
  /** Case ids in the current filtered order, for Alt+↓ / Alt+↑ */
  order: string[]
  setFilter: (patch: Partial<CaseFilter>) => void
  /** Set one `var.{name}` filter; empty removes it (VAR-10) */
  setVarFilter: (name: string, value: string) => void
  clearFilter: () => void
  toggle: (cid: string, open?: boolean) => void
  setOrder: (ids: string[]) => void
}

export const useExplorer = create<ExplorerState>()((set) => ({
  filter: {},
  expanded: {},
  order: [],
  setFilter: (patch) => set((s) => ({ filter: { ...s.filter, ...patch } })),
  setVarFilter: (name, value) =>
    set((s) => {
      const vars = { ...s.filter.vars }
      if (value) vars[name] = value
      else delete vars[name]
      return { filter: { ...s.filter, vars } }
    }),
  clearFilter: () => set({ filter: {} }),
  toggle: (cid, open) => set((s) => ({ expanded: { ...s.expanded, [cid]: open ?? !s.expanded[cid] } })),
  setOrder: (order) => set({ order }),
}))

export const activeFilterCount = (f: CaseFilter) =>
  [f.phase, f.status, f.warning, f.voi, f.showExcluded].filter(Boolean).length +
  Object.values(f.vars ?? {}).filter(Boolean).length

/** Variable-driven columns and colour of the case list, per project (VAR-10, UI-13) */
interface ViewPrefs {
  columns: string[]
  colorBy: string | null
}
interface ExplorerPrefs {
  byProject: Record<string, ViewPrefs>
  toggleColumn: (pid: string, name: string) => void
  setColorBy: (pid: string, name: string | null) => void
}
const EMPTY: ViewPrefs = { columns: [], colorBy: null }

export const useExplorerPrefs = create<ExplorerPrefs>()(
  persist(
    (set) => ({
      byProject: {},
      toggleColumn: (pid, name) =>
        set((s) => {
          const cur = s.byProject[pid] ?? EMPTY
          const columns = cur.columns.includes(name) ? cur.columns.filter((c) => c !== name) : [...cur.columns, name]
          return { byProject: { ...s.byProject, [pid]: { ...cur, columns } } }
        }),
      setColorBy: (pid, colorBy) =>
        set((s) => ({ byProject: { ...s.byProject, [pid]: { ...(s.byProject[pid] ?? EMPTY), colorBy } } })),
    }),
    { name: 'rw.explorer' },
  ),
)

export const usePrefs = (pid: string): ViewPrefs => useExplorerPrefs((s) => s.byProject[pid] ?? EMPTY)
