import { create } from 'zustand'

type Shown = 'storage' | 'compute' | null

export const useSetup = create<{ shown: Shown; show: (shown: Shown) => void }>()((set) => ({
  shown: null,
  show: (shown) => set({ shown }),
}))
