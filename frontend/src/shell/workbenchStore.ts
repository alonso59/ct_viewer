// Workbench controller: editor tabs (dockview), palette state, toasts. No domain logic.
import type { DockviewApi } from 'dockview-react'
import { create } from 'zustand'

import { registry } from './registry'
import { problemToastText } from '../lib/problem'

export interface EditorParams {
  type: string
  preview?: boolean
  [k: string]: unknown
}

export interface Toast {
  id: number
  message: string
  tone?: 'info' | 'ok' | 'warn' | 'error'
  action?: { label: string; run: () => void }
}

interface WorkbenchState {
  pid: string | null
  dock: DockviewApi | null
  active: EditorParams | null
  palette: null | 'commands' | 'quickopen'
  toasts: Toast[]
  /** Bumped when the active editor's URL inputs change outside its params (e.g. viewer layout) */
  urlToken: number
  setDock: (dock: DockviewApi | null) => void
  setActive: (p: EditorParams | null) => void
  openPalette: (mode: 'commands' | 'quickopen' | null) => void
  toast: (t: Omit<Toast, 'id'>) => void
  dismissToast: (id: number) => void
}

let toastId = 0

export const useWorkbench = create<WorkbenchState>()((set) => ({
  pid: null,
  dock: null,
  active: null,
  palette: null,
  toasts: [],
  urlToken: 0,
  setDock: (dock) => set({ dock }),
  setActive: (active) => set({ active }),
  openPalette: (palette) => set({ palette }),
  toast: (t) => {
    const id = ++toastId
    set((s) => ({ toasts: [...s.toasts.slice(-3), { ...t, id }] }))
    setTimeout(() => useWorkbench.getState().dismissToast(id), 6000)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

/** An open asked for while the editor area (lazy, NFR-07) is still loading; run once it is ready */
let pendingOpen: { pid: string; args: Parameters<typeof openEditor> } | null = null

/** EditorArea: open what was asked for while it loaded; returns it, so a dock that is disposed
 *  again at once (React StrictMode mounts twice in dev) can hand it back with `requeueOpen` */
export function flushPendingOpen(pid: string): Parameters<typeof openEditor> | null {
  const p = pendingOpen
  pendingOpen = null
  if (!p || p.pid !== pid) return null
  openEditor(...p.args)
  return p.args
}

export function requeueOpen(pid: string, args: Parameters<typeof openEditor>) {
  pendingOpen ??= { pid, args }
}

/** Open (or focus) an editor tab. Preview tabs reuse one slot until pinned (UI-03). */
export function openEditor(type: string, params: Record<string, unknown> = {}, opts: { preview?: boolean } = {}) {
  const dock = useWorkbench.getState().dock
  const contrib = registry.getEditor<Record<string, unknown>>(type)
  if (!contrib || !registry.allowed(contrib)) return
  if (!dock) {
    // the last request wins, like a click that replaces the preview tab
    const pid = useWorkbench.getState().pid
    if (pid) pendingOpen = { pid, args: [type, params, opts] }
    return
  }
  const id = contrib.id(params)
  const existing = dock.getPanel(id)
  if (existing) {
    if (!opts.preview && (existing.params as EditorParams | undefined)?.preview)
      existing.api.updateParameters({ ...existing.params, preview: false })
    else if (JSON.stringify({ ...existing.params, preview: undefined }) !== JSON.stringify({ type, ...params, preview: undefined }))
      existing.api.updateParameters({ ...existing.params, ...params })
    existing.api.setActive()
    return
  }
  const preview = opts.preview ?? false
  const previewPanel = preview ? dock.panels.find((p) => (p.params as EditorParams | undefined)?.preview) : undefined
  const position = previewPanel
    ? { referencePanel: previewPanel.id, direction: 'within' as const }
    : dock.activePanel
      ? { referencePanel: dock.activePanel.id, direction: 'within' as const }
      : undefined
  dock.addPanel({
    id,
    component: 'editor',
    tabComponent: 'editorTab',
    title: contrib.title(params),
    params: { type, ...params, preview },
    position,
  })
  previewPanel?.api.close()
}

export function pinEditor(panelId: string) {
  const p = useWorkbench.getState().dock?.getPanel(panelId)
  if (p && (p.params as EditorParams | undefined)?.preview) p.api.updateParameters({ ...p.params, preview: false })
}

export function closeActiveEditor() {
  useWorkbench.getState().dock?.activePanel?.api.close()
}

export function closeOtherEditors() {
  const dock = useWorkbench.getState().dock
  const active = dock?.activePanel
  if (!dock || !active) return
  for (const p of [...dock.panels]) if (p.id !== active.id && p.group === active.group) p.api.close()
}

export function splitActiveEditor() {
  const dock = useWorkbench.getState().dock
  const active = dock?.activePanel
  if (!dock || !active) return
  const params = active.params as EditorParams
  const contrib = registry.getEditor<Record<string, unknown>>(params.type)
  if (!contrib) return
  dock.addPanel({
    id: `${active.id}#${Date.now().toString(36)}`,
    component: 'editor',
    tabComponent: 'editorTab',
    title: active.title ?? '',
    params: { ...params, preview: false },
    position: { referencePanel: active.id, direction: 'right' },
  })
}

/** Update the active tab's params (and so the URL), e.g. after switching items in a case tab */
export function updateActiveParams(panelId: string, patch: Record<string, unknown>) {
  const { dock, setActive } = useWorkbench.getState()
  const panel = dock?.getPanel(panelId)
  if (!panel) return
  const next = { ...(panel.params as EditorParams), ...patch }
  panel.api.updateParameters(next)
  if (dock?.activePanel?.id === panelId) setActive(next)
}

export const refreshUrl = () => useWorkbench.setState((s) => ({ urlToken: s.urlToken + 1 }))

export const toast = (t: Omit<Toast, 'id'>) => useWorkbench.getState().toast(t)
/** UI-18 (AUD-A6-12): an error toast with the problem's cause and next steps */
export const toastProblem = (e: unknown, fallback?: string) => toast({ message: problemToastText(e, fallback), tone: 'error' })
