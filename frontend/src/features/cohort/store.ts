import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { CohortSort, Variable, VariableCategory, VariableOrigin } from '../../api'

/** The navigator's open selection: an origin group, or one of Metadata's categories */
export interface GroupSelection {
  origin: VariableOrigin
  category: VariableCategory | null
}

/** Origin groups in navigator order */
export const ORIGINS: VariableOrigin[] = ['metadata', 'automatic', 'review', 'clinical', 'derived']
/** Metadata categories in navigator order */
export const CATEGORIES: VariableCategory[] = ['patient', 'study', 'series', 'equipment', 'technique', 'contrast', 'geometry', 'intensity', 'dates', 'phase_readiness', 'provenance', 'dataset']

/** The selection's variables, in catalog order; `null` selects nothing */
export const variablesOf = (vars: Variable[], sel: GroupSelection | null): Variable[] =>
  sel === null ? [] : vars.filter((v) => v.origin === sel.origin && (sel.origin !== 'metadata' || v.category === sel.category))

/** The grid's filters: variable values (OR within a variable), a phase, text on case / patient ID */
export interface CohortFilters {
  vars: Record<string, string[]>
  phase: string
  q: string
}

export const EMPTY_FILTERS: CohortFilters = { vars: {}, phase: '', q: '' }

interface ProjectState {
  group: GroupSelection | null
  /** Pinned variables stay grid columns no matter which group is open */
  pinned: string[]
  /** Case rows the grid shows expanded */
  expanded: Record<string, boolean>
  filters: CohortFilters
}

interface CohortState extends ProjectState {
  /** The project whose group, pins, expansion and filters these are */
  pid: string | null
  /** Each project's open group, pins, expansion and filters, kept across reloads */
  byProject: Record<string, ProjectState>
  /** A case the grid should reveal (an external entry point); not kept across reloads */
  focusCase: string | null
  /** What the panels under the filters show; not kept across reloads */
  compareCase: string | null
  summaryColumn: string | null
  tagsItem: string | null
  timelineCase: string | null
  /** The balance check panel: open, with its two variables */
  balance: { a: string; b: string } | null
  sort: CohortSort | null
  /** The clinical cell being edited: a case row (`scanIdx` null) or a scan row */
  editing: { caseId: string; scanIdx: string | null; column: string } | null
  setBalance: (balance: CohortState['balance']) => void
  setTimeline: (caseId: string | null) => void
  setSort: (sort: CohortSort | null) => void
  setEditing: (cell: CohortState['editing']) => void
  setCompare: (caseId: string | null) => void
  setSummary: (column: string | null) => void
  setTags: (itemId: string | null) => void
  /** Reveal a case in the grid */
  focus: (caseId: string) => void
  /** Show a project's own state (none the first time) */
  openProject: (pid: string) => void
  setGroup: (group: GroupSelection | null) => void
  togglePin: (name: string) => void
  toggleExpanded: (caseId: string, open?: boolean) => void
  addVarValue: (name: string, value: string | string[]) => void
  removeVarValue: (name: string, value?: string) => void
  setPhase: (phase: string) => void
  setQ: (q: string) => void
  clearFilters: () => void
}

export const useCohort = create<CohortState>()(persist((set) => ({
  pid: null,
  byProject: {},
  focusCase: null,
  compareCase: null,
  summaryColumn: null,
  tagsItem: null,
  sort: null,
  editing: null,
  balance: null,
  timelineCase: null,
  setBalance: (balance) => set({ balance }),
  setTimeline: (timelineCase) => set({ timelineCase }),
  setSort: (sort) => set({ sort }),
  setEditing: (editing) => set({ editing }),
  setCompare: (compareCase) => set({ compareCase }),
  setSummary: (summaryColumn) => set({ summaryColumn }),
  setTags: (tagsItem) => set({ tagsItem }),
  group: null,
  pinned: [],
  expanded: {},
  filters: EMPTY_FILTERS,
  focus: (caseId) => set({ focusCase: caseId }),
  openProject: (pid) => set((s) => ({
    pid,
    focusCase: null,
    compareCase: null,
    summaryColumn: null,
    tagsItem: null,
    sort: null,
    editing: null,
    balance: null,
    timelineCase: null,
    group: s.byProject[pid]?.group ?? null,
    pinned: s.byProject[pid]?.pinned ?? [],
    expanded: s.byProject[pid]?.expanded ?? {},
    filters: s.byProject[pid]?.filters ?? EMPTY_FILTERS,
  })),
  setGroup: (group) => set({ group }),
  togglePin: (name) => set((s) => ({ pinned: s.pinned.includes(name) ? s.pinned.filter((p) => p !== name) : [...s.pinned, name] })),
  toggleExpanded: (caseId, open) => set((s) => ({ expanded: { ...s.expanded, [caseId]: open ?? !s.expanded[caseId] } })),
  addVarValue: (name, value) => set((s) => {
    const values = Array.isArray(value) ? value : [value]
    const cur = s.filters.vars[name] ?? []
    const next = [...cur, ...values.filter((x) => x !== '' && !cur.includes(x))]
    if (next.length === cur.length) return {}
    return { filters: { ...s.filters, vars: { ...s.filters.vars, [name]: next } } }
  }),
  removeVarValue: (name, value) => set((s) => {
    const cur = s.filters.vars[name]
    if (!cur) return {}
    const vars = { ...s.filters.vars }
    if (value === undefined) delete vars[name]
    else {
      const kept = cur.filter((x) => x !== value)
      if (kept.length) vars[name] = kept
      else delete vars[name]
    }
    return { filters: { ...s.filters, vars } }
  }),
  setPhase: (phase) => set((s) => ({ filters: { ...s.filters, phase } })),
  setQ: (q) => set((s) => ({ filters: { ...s.filters, q } })),
  clearFilters: () => set({ filters: EMPTY_FILTERS }),
}), { name: 'rw.cohort.state', partialize: ({ byProject }) => ({ byProject }) }))

// Every change of the open project's state is that project's to keep
useCohort.subscribe((s, prev) => {
  if (s.pid && (s.group !== prev.group || s.pinned !== prev.pinned || s.expanded !== prev.expanded || s.filters !== prev.filters))
    useCohort.setState({ byProject: { ...s.byProject, [s.pid]: { group: s.group, pinned: s.pinned, expanded: s.expanded, filters: s.filters } } })
})
