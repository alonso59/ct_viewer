// The last view of each project item (window, crosshair, label visibility), kept across reloads.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { Vec3 } from './model/types'

export interface ItemView {
  ww: number
  wl: number
  ras: Vec3
  labels: Record<number, boolean>
}

/** Items remembered; the one viewed longest ago goes first */
export const MAX_REMEMBERED = 100

interface Memory {
  items: Record<string, ItemView>
  /** Keys, the most recent last */
  order: string[]
  remember: (key: string, view: ItemView) => void
}

export const useItemMemory = create<Memory>()(persist((set) => ({
  items: {},
  order: [],
  remember: (key, view) =>
    set((s) => {
      const order = [...s.order.filter((k) => k !== key), key]
      const dropped = order.slice(0, Math.max(0, order.length - MAX_REMEMBERED))
      const items = { ...s.items, [key]: view }
      for (const k of dropped) delete items[k]
      return { items, order: order.slice(dropped.length) }
    }),
}), { name: 'rw.viewer.items', partialize: ({ items, order }) => ({ items, order }) }))
