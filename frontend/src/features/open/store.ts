import { create } from 'zustand'

/** "Open file or folder…" (UI-17) */
export const useOpenDialog = create<{ open: boolean; show: () => void; hide: () => void }>()((set) => ({
  open: false,
  show: () => set({ open: true }),
  hide: () => set({ open: false }),
}))
