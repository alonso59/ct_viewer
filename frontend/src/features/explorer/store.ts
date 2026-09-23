import { create } from 'zustand'

import type { CaseFilter } from '../../api'

interface ExplorerState {
  filter: CaseFilter
  expanded: Record<string, boolean>
  /** Case ids in the current filtered order, for Alt+↓ / Alt+↑ */
  order: string[]
  setFilter: (patch: Partial<CaseFilter>) => void
  clearFilter: () => void
  toggle: (cid: string, open?: boolean) => void
  setOrder: (ids: string[]) => void
}

export const useExplorer = create<ExplorerState>()((set) => ({
  filter: {},
  expanded: {},
  order: [],
  setFilter: (patch) => set((s) => ({ filter: { ...s.filter, ...patch } })),
  clearFilter: () => set({ filter: {} }),
  toggle: (cid, open) => set((s) => ({ expanded: { ...s.expanded, [cid]: open ?? !s.expanded[cid] } })),
  setOrder: (order) => set({ order }),
}))

export const activeFilterCount = (f: CaseFilter) =>
  [f.group, f.phase, f.status, f.warning, f.voi, f.showExcluded].filter(Boolean).length
