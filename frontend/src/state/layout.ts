// Shell layout state, persisted per project (UI-13).
import { create } from 'zustand'

export interface LayoutState {
  sidebarVisible: boolean
  sidebarWidth: number
  imageSectionOpen: boolean
  panelVisible: boolean
  /** Height set by the user (sash, maximize); `null` = the automatic default (`panelAutoHeight`) */
  panelHeight: number | null
  inspectorVisible: boolean
  inspectorWidth: number
  activeView: string
  activePanelTab: string
  /** UI-13 (AUD-A1-18): bottom panel visibility per editor type; unknown types use `panelDefault` */
  panelByEditor: Record<string, boolean>
}

/** Editors that fill the height with a form or charts (radiomics settings, a dashboard, a task, project
 *  settings): the panel starts closed there; elsewhere (welcome, queue, tables) it starts open */
const FULL_HEIGHT = new Set(['radiomics', 'run', 'task', 'settings'])
/** Editors whose panel stays closed until a panel tab has content for them (AUD-A3-01): a case tab
 *  opens it for a feature row or a problem of its item, so the viewer keeps the height otherwise */
const CONTENT_FIRST = new Set(['case'])
export const panelDefault = (editorType: string | null) => !FULL_HEIGHT.has(editorType ?? '') && !CONTENT_FIRST.has(editorType ?? '')
/** Default panel height: at most 220 px and about 20 % of the window (AUD-A3-01) */
export const panelAutoHeight = (viewport = window.innerHeight) => Math.min(220, Math.round(viewport * 0.2))
/** The height of the pre-FB6 default, stored by every save: read as "automatic" */
const OLD_DEFAULT_HEIGHT = 220

const DEFAULTS: LayoutState = {
  sidebarVisible: true,
  sidebarWidth: 300,
  imageSectionOpen: true,
  panelVisible: true,
  panelHeight: null,
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
  /** AUD-A3-01: which panel tabs have content for the active item (not persisted) */
  panelContent: Record<string, boolean>
  /** A panel tab reports whether it has content; a content-first editor (a case tab) opens its
   *  panel on the first tab with content and closes it when none has, unless the user chose */
  setPanelContent: (tab: string, has: boolean) => void
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

/** AUD-A3-01: the panel of a content-first editor follows its content (never remembered) */
function followContent() {
  const s = useLayout.getState()
  const type = s.editorType ?? ''
  if (!CONTENT_FIRST.has(type) || s.panelByEditor[type] !== undefined) return
  const tab = Object.keys(s.panelContent).find((k) => s.panelContent[k])
  if (!tab) {
    if (s.panelVisible) useLayout.setState({ panelVisible: false })
  } else if (!s.panelVisible) useLayout.setState({ panelVisible: true, activePanelTab: s.panelContent[s.activePanelTab] ? s.activePanelTab : tab })
}

export const useLayout = create<Store>()((set, get) => ({
  ...DEFAULTS,
  pid: null,
  editorType: null,
  setEditorType: (type) => {
    const s = get()
    if (s.editorType === type) return
    set({ editorType: type, panelVisible: s.panelByEditor[type ?? ''] ?? panelDefault(type) })
    followContent()
  },
  panelContent: {},
  setPanelContent: (tab, has) => {
    const cur = get().panelContent
    if (tab in cur && cur[tab] === has) return
    set((s) => ({ panelContent: { ...s.panelContent, [tab]: has } }))
    followContent()
  },
  load: (pid) => {
    let stored: Partial<LayoutState> = {}
    try {
      stored = JSON.parse(localStorage.getItem(key(pid)) ?? '{}') as Partial<LayoutState>
    } catch {
      stored = {}
    }
    if (stored.panelHeight === OLD_DEFAULT_HEIGHT) stored.panelHeight = null
    set({ ...DEFAULTS, ...stored, pid, editorType: null, panelContent: {} })
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
