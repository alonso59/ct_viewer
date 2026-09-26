// Help dialogs state (the dialogs load on first open, NFR-07)
import { create } from 'zustand'

export const useHelp = create<{ open: 'keys' | 'about' | null; show: (d: 'keys' | 'about' | null) => void }>()((set) => ({
  open: null,
  show: (open) => set({ open }),
}))
