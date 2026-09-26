// "New table…" can be asked for from the palette (AUD-A1-06) as well as from the Labeling view
import { create } from 'zustand'

export const useNewTable = create<{ open: boolean; set: (open: boolean) => void }>()((set) => ({ open: false, set: (open) => set({ open }) }))
