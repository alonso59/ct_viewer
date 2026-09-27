// User preferences (Settings view). Per browser, in localStorage.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import { applySize, type InterfaceSize, type ThemeChoice } from '../theme'

interface SettingsState {
  theme: ThemeChoice
  /** UI-27 (AUD-A3-16): scale of every font and control size; Default = 14 px UI */
  uiSize: InterfaceSize
  rowDensity: 'thumbnails' | 'compact'
  /** UI-12: command id → key chord overrides */
  keybindings: Record<string, string>
  set: (patch: Partial<Omit<SettingsState, 'set' | 'setKeybinding'>>) => void
  setKeybinding: (command: string, chord: string | null) => void
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      theme: 'dark',
      uiSize: 'default',
      rowDensity: 'thumbnails',
      keybindings: {},
      set: (patch) => set(patch),
      setKeybinding: (command, chord) =>
        set((s) => {
          const next = { ...s.keybindings }
          if (chord) next[command] = chord
          else delete next[command]
          return { keybindings: next }
        }),
    }),
    { name: 'rw.settings' },
  ),
)

// UI-27: the size set applies synchronously (before React re-renders), so views that measure rows
// (the Explorer's virtual list) read the new tokens
applySize(useSettings.getState().uiSize)
useSettings.subscribe((s, prev) => {
  if (s.uiSize !== prev.uiSize) applySize(s.uiSize)
})
