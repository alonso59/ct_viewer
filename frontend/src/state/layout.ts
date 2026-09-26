// Shell layout state, persisted per project (UI-13).
import { create } from 'zustand'

export interface LayoutState {
  sidebarVisible: boolean
  sidebarWidth: number
  imageSectionOpen: boolean
  panelVisible: boolean
  panelHeight: number
  inspectorVisible: boolean
  inspectorWidth: number
  activeView: string
  activePanelTab: string
  /** UI-13 (AUD-A1-18): bottom panel visibility per editor type; unknown types use `panelDefault` */
  panelByEditor: Record<string, boolean>
}

/** Editors that fill the height with a form or charts (radiomics settings, a dashboard, a task, project
 *  settings): the panel starts closed there; elsewhere (case, welcome, queue, tables) it starts open */
const FULL_HEIGHT = new Set(['radiomics', 'run', 'task', 'settings'])
export const panelDefault = (editorType: string | null) => !FULL_HEIGHT.has(editorType ?? '')

const DEFAULTS: LayoutState = {
  sidebarVisible: true,
  sidebarWidth: 300,
  imageSectionOpen: true,
  panelVisible: true,
  panelHeight: 220,
  inspectorVisible: false,
  inspectorWidth: 300,
  activeView: 'project',
  activePanelTab: 'measurements',
  panelByEditor: {},
}

const key = (pid: string) => `rw.layout.${pid}`

interface Store extends LayoutState {
  pid: string | null
  /** Type of the active editor tab (not persisted) */
  editorType: string | null
  setEditorType: (type: string | null) => void
  load: (pid: string) => void
  set: (patch: Partial<LayoutState>) => void
  toggle: (k: 'sidebarVisible' | 'panelVisible' | 'inspectorVisible' | 'imageSectionOpen') => void
  showView: (id: string) => void
  showPanelTab: (id: string) => void
}

function save(s: Store) {
  if (!s.pid) return
  const data = Object.fromEntries(Object.keys(DEFAULTS).map((k) => [k, s[k as keyof LayoutState]]))
  try {
    localStorage.setItem(key(s.pid), JSON.stringify(data))
  } catch {
    // session-only layout
  }
}

export const useLayout = create<Store>()((set, get) => ({
  ...DEFAULTS,
  pid: null,
  editorType: null,
  setEditorType: (type) => {
    const s = get()
    if (s.editorType === type) return
    set({ editorType: type, panelVisible: s.panelByEditor[type ?? ''] ?? panelDefault(type) })
  },
  load: (pid) => {
    let stored: Partial<LayoutState> = {}
    try {
      stored = JSON.parse(localStorage.getItem(key(pid)) ?? '{}') as Partial<LayoutState>
    } catch {
      stored = {}
    }
    set({ ...DEFAULTS, ...stored, pid, editorType: null })
  },
  set: (patch) => {
    // a panel shown or hidden by the user is remembered for the active editor type
    const s = get()
    const extra = patch.panelVisible !== undefined ? { panelByEditor: { ...s.panelByEditor, [s.editorType ?? '']: patch.panelVisible } } : {}
    set({ ...patch, ...extra })
    save(get())
  },
  toggle: (k) => get().set({ [k]: !get()[k] }),
  // Clicking the active view's icon collapses the side bar, like VS Code
  showView: (id) => {
    const s = get()
    if (s.activeView === id && s.sidebarVisible) s.set({ sidebarVisible: false })
    else s.set({ activeView: id, sidebarVisible: true })
  },
  showPanelTab: (id) => get().set({ activePanelTab: id, panelVisible: true }),
}))
