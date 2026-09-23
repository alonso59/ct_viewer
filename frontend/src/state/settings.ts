// User preferences (Settings view). Per browser, in localStorage.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { ThemeChoice } from '../theme'

interface SettingsState {
  theme: ThemeChoice
  rowDensity: 'thumbnails' | 'compact'
  simulateReviewer: boolean
  /** UI-12: command id → key chord overrides */
  keybindings: Record<string, string>
  set: (patch: Partial<Omit<SettingsState, 'set' | 'setKeybinding'>>) => void
  setKeybinding: (command: string, chord: string | null) => void
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      theme: 'dark',
      rowDensity: 'thumbnails',
      simulateReviewer: true,
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
