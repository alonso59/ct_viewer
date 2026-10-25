// Project dialogs that commands open as well as buttons
import { create } from 'zustand'

interface ProjectDialogs {
  creating: boolean
  /** Bumped by "Import project bundle…": the home opens its file picker */
  bundlePick: number
  archive: { pid: string; name: string; home: boolean } | null
  /** Relink asked for from a command or a missing-image card: the project id */
  relink: string | null
  set: (patch: Partial<Omit<ProjectDialogs, 'set'>>) => void
}

export const useProjectDialogs = create<ProjectDialogs>()((set) => ({
  creating: false,
  bundlePick: 0,
  archive: null,
  relink: null,
  set: (patch) => set(patch),
}))
