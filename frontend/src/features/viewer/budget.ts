// VW-14 memory budget: at most `maxLoaded` case tabs keep their volumes. The active tab is always
// loaded; hidden tabs beyond the budget are unloaded (least recently shown first) and reload on focus.
import { useEffect } from 'react'
import { create } from 'zustand'

interface BudgetState {
  maxLoaded: number
  /** Most recently shown first */
  order: string[]
}

export const useBudget = create<BudgetState>()(() => ({ maxLoaded: 3, order: [] }))

/** UI runtime config (API-01 `ui_config.viewer_max_loaded`) */
export function configureViewer(cfg: { maxLoaded?: number }) {
  if (cfg.maxLoaded && cfg.maxLoaded > 0) useBudget.setState({ maxLoaded: Math.floor(cfg.maxLoaded) })
}

export function isLoaded(order: string[], max: number, id: string): boolean {
  const i = order.indexOf(id)
  return i >= 0 && i < max
}

/** Registers a tab and returns whether it may hold volumes right now */
export function useLoadBudget(id: string, active: boolean): boolean {
  useEffect(() => {
    if (!active) {
      // Hidden but not closed: remember it (at the back if it was never shown)
      useBudget.setState((s) => (s.order.includes(id) ? s : { order: [...s.order, id] }))
      return
    }
    useBudget.setState((s) => ({ order: [id, ...s.order.filter((x) => x !== id)] }))
  }, [id, active])
  useEffect(() => () => useBudget.setState((s) => ({ order: s.order.filter((x) => x !== id) })), [id])
  return useBudget((s) => active || isLoaded(s.order, s.maxLoaded, id))
}
