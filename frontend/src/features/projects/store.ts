// Project dialogs that commands open as well as buttons (AUD-A1-01, AUD-A4-03)
import { create } from 'zustand'

interface ProjectDialogs {
  /** New project (UI-04) */
  creating: boolean
  /** Bumped by "Import project bundle…": the home opens its file picker (PRJ-09) */
  bundlePick: number
  /** Archive confirmation (PRJ-06) */
  archive: { pid: string; name: string; home: boolean } | null
  set: (patch: Partial<Omit<ProjectDialogs, 'set'>>) => void
}

export const useProjectDialogs = create<ProjectDialogs>()((set) => ({
  creating: false,
  bundlePick: 0,
  archive: null,
  set: (patch) => set(patch),
}))
