// Navigation context (AUD-A1-04, UI_SHELL §Navigation context): a case opened from a list
// (Outliers, correction queue, Problems, a label table) remembers that list, so Alt+↓ / Alt+↑
// follow it; the case header shows "Outliers 3/22" with × to fall back to Explorer order.
import { create } from 'zustand'

export interface NavEntry {
  caseId: string
  /** null = the case (its default item) */
  itemId: string | null
}

interface NavContextState {
  /** Translated list name, e.g. "Outliers" or a label table's name; null = Explorer order */
  label: string | null
  entries: NavEntry[]
  /** Last position stepped to or opened */
  index: number
  set: (label: string, entries: NavEntry[], index: number) => void
  setIndex: (index: number) => void
  clear: () => void
}

export const useNavContext = create<NavContextState>()((set) => ({
  label: null,
  entries: [],
  index: -1,
  set: (label, entries, index) => set({ label, entries, index }),
  setIndex: (index) => set({ index }),
  clear: () => set({ label: null, entries: [], index: -1 }),
}))

const matches = (e: NavEntry | undefined, caseId: string, itemId: string | null) =>
  !!e && e.caseId === caseId && (e.itemId === null || itemId === null || e.itemId === itemId)

/** Position of the active case / item in the context, or null when it is not in the list */
export function navPosition(s: Pick<NavContextState, 'label' | 'entries' | 'index'>, caseId: string | null, itemId: string | null): number | null {
  if (!s.label || !caseId) return null
  if (matches(s.entries[s.index], caseId, itemId)) return s.index
  const exact = s.entries.findIndex((e) => e.caseId === caseId && e.itemId === itemId)
  if (exact >= 0) return exact
  const byCase = s.entries.findIndex((e) => e.caseId === caseId)
  return byCase >= 0 ? byCase : null
}

/** Drop repeated entries (e.g. one outlier row per label of the same item), keeping the order */
export function uniqueEntries(entries: NavEntry[]): NavEntry[] {
  const seen = new Set<string>()
  return entries.filter((e) => {
    const k = `${e.caseId}|${e.itemId ?? ''}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}
