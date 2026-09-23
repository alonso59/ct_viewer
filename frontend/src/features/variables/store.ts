// Variables view UI state: collapsed sections and which dialog is open
import { create } from 'zustand'

type Dialog = 'derived' | 'external' | null

interface VariablesUi {
  collapsed: Record<string, boolean>
  dialog: Dialog
  toggleSection: (section: string, shut: boolean) => void
  openDialog: (d: Dialog) => void
}

export const useVariablesUi = create<VariablesUi>()((set) => ({
  collapsed: {},
  dialog: null,
  toggleSection: (section, shut) => set((s) => ({ collapsed: { ...s.collapsed, [section]: shut } })),
  openDialog: (dialog) => set({ dialog }),
}))
