// Editor area on dockview: tabs, preview mode, drag, split; tabs persist per project.
import {
  DockviewReact,
  type DockviewReadyEvent,
  type IDockviewPanelHeaderProps,
  type IDockviewPanelProps,
} from 'dockview-react'
import { Suspense, useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router'

import { Icon, codicon } from '../theme'
import { registry } from './registry'
import { flushPendingOpen, openEditor, pinEditor, requeueOpen, useWorkbench, type EditorParams } from './workbenchStore'

const THEME = { name: 'rw', className: 'dockview-theme-dark dv-rw', gap: 0 }
const tabsKey = (pid: string) => `rw.tabs.${pid}`

/** The saved dockview layout of one project's editor tabs, or null (none, unreadable) */
export function loadTabs(pid: string): unknown {
  try {
    const saved = localStorage.getItem(tabsKey(pid))
    return saved ? (JSON.parse(saved) as unknown) : null
  } catch {
    return null
  }
}

export function saveTabs(pid: string, layout: unknown) {
  try {
    localStorage.setItem(tabsKey(pid), JSON.stringify(layout))
  } catch {
    // storage unavailable
  }
}

function EditorHost(props: IDockviewPanelProps<EditorParams>) {
  const { t } = useTranslation()
  const subscribe = useCallback((changed: () => void) => {
    const d = props.api.onDidActiveChange(changed)
    return () => d.dispose()
  }, [props.api])
  const getActive = useCallback(() => props.api.isActive, [props.api])
  const active = useSyncExternalStore(subscribe, getActive)
  const contrib = registry.getEditor<EditorParams>(props.params.type)
  if (!contrib) return <div className="empty">{t('shell.unknownEditor', { type: props.params.type })}</div>
  const C = contrib.component
  return (
    <div className="editor-host">
      <Suspense fallback={<div className="empty">{t('common.loading')}</div>}>
        <C params={props.params} panelId={props.api.id} active={active} />
      </Suspense>
    </div>
  )
}

function EditorTab(props: IDockviewPanelHeaderProps<EditorParams>) {
  const { t } = useTranslation()
  const contrib = registry.getEditor<EditorParams>(props.params.type)
  const [title, setTitle] = useState(props.api.title ?? '')
  useEffect(() => {
    const d = props.api.onDidTitleChange((e) => setTitle(e.title))
    return () => d.dispose()
  }, [props.api])
  return (
    <div
      className="etab"
      data-preview={props.params.preview === true}
      onDoubleClick={() => pinEditor(props.api.id)}
      onAuxClick={(e) => e.button === 1 && props.api.close()}
      title={props.params.preview ? t('shell.previewTab') : title}
    >
      {contrib ? <Icon spec={contrib.icon(props.params)} /> : null}
      <span className="etab-title">{title}</span>
      <button
        type="button"
        className="icon-btn etab-close"
        aria-label={t('shell.closeTab')}
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation()
          props.api.close()
        }}
      >
        <Icon spec={codicon('close')} />
      </button>
    </div>
  )
}

function Watermark() {
  const C = registry.getEditor('welcome')?.component
  return C ? <C params={{}} panelId="watermark" active /> : null
}

function pathFor(pid: string, p: EditorParams | null): string {
  if (!p) return `/p/${pid}`
  const contrib = registry.getEditor<EditorParams>(p.type)
  return contrib?.path?.(pid, p) ?? `/p/${pid}`
}

/** A different path or item is a new history entry; other query changes (layout) are not */
export function isNewEntry(from: string, to: string): boolean {
  const a = new URL(from, 'http://x')
  const b = new URL(to, 'http://x')
  return a.pathname !== b.pathname || a.searchParams.get('item') !== b.searchParams.get('item')
}

function matchLocation(pid: string, pathname: string, search: string): EditorParams | null {
  const rest = pathname.slice(`/p/${pid}`.length) || '/'
  const sp = new URLSearchParams(search)
  for (const e of registry.editors.values()) {
    if (!registry.allowed(e)) continue
    const m = (e as unknown as { match?: (p: string, s: URLSearchParams) => Record<string, unknown> | null }).match?.(rest, sp)
    if (m) return { type: e.type, ...m }
  }
  return null
}

export function EditorArea({ pid }: { pid: string }) {
  const setDock = useWorkbench((s) => s.setDock)
  const setActive = useWorkbench((s) => s.setActive)
  const location = useLocation()
  const navigate = useNavigate()
  const lastPath = useRef<string>('')
  const ready = useRef(false)
  const flushed = useRef<ReturnType<typeof flushPendingOpen>>(null)

  const onReady = (e: DockviewReadyEvent) => {
    setDock(e.api)
    const saved = loadTabs(pid)
    try {
      if (saved) e.api.fromJSON(saved as Parameters<typeof e.api.fromJSON>[0])
    } catch {
      e.api.clear()
    }
    e.api.onDidLayoutChange(() => saveTabs(pid, e.api.toJSON()))
    e.api.onDidActivePanelChange(({ panel }) => setActive((panel?.params as EditorParams | undefined) ?? null))
    const initial = matchLocation(pid, location.pathname, location.search)
    if (initial) {
      const { type, ...params } = initial
      openEditor(type, params)
    } else if (e.api.activePanel) {
      setActive(e.api.activePanel.params as EditorParams)
    }
    ready.current = true
    // a tab asked for while this lazy area was loading (e.g. a case double-clicked at once)
    flushed.current = flushPendingOpen(pid)
    // StrictMode disposes and re-creates the dock in the same commit; a later unmount must not
    setTimeout(() => (flushed.current = null), 0)
  }

  const reconcileLocation = useCallback((pathname: string, search: string) => {
    if (!ready.current) return
    const prefix = `/p/${pid}`
    if (pathname !== prefix && !pathname.startsWith(`${prefix}/`)) return
    const path = pathname + search
    if (path === lastPath.current) return
    const m = matchLocation(pid, pathname, search)
    if (m) {
      lastPath.current = path
      const { type, ...params } = m
      openEditor(type, params)
    }
  }, [pid])

  // Deep links and router navigation open the matching editor.
  useEffect(() => {
    reconcileLocation(location.pathname, location.search)
  }, [location.pathname, location.search, reconcileLocation])

  // Back may arrive before a deferred router transition commits. Its pathname can then
  // equal the previous render even though the dock already moved to another case.
  useEffect(() => {
    const onPop = () => reconcileLocation(window.location.pathname, window.location.search)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [reconcileLocation])

  // The active editor drives the URL: a new tab, case or item is a history entry, so browser
  // Back returns to it; a layout or other query tweak replaces the entry
  const active = useWorkbench((s) => s.active)
  const urlToken = useWorkbench((s) => s.urlToken)
  // `navigate` changes with every location; as a dependency it would re-run this effect on
  // browser Back with the previous tab still in `active` and push that tab again
  const nav = useRef(navigate)
  useEffect(() => {
    nav.current = navigate
  }, [navigate])
  useEffect(() => {
    // History reconciliation may have activated another panel earlier in this effect flush.
    if (!ready.current || active !== useWorkbench.getState().active) return
    const path = pathFor(pid, active)
    if (path !== lastPath.current) {
      const replace = !lastPath.current || !isNewEntry(lastPath.current, path)
      lastPath.current = path
      nav.current(path, { replace })
    }
  }, [active, urlToken, pid])

  useEffect(
    () => () => {
      setDock(null)
      // disposed right after it opened a pending tab (StrictMode's second mount): hand it back
      if (flushed.current) requeueOpen(pid, flushed.current)
      flushed.current = null
    },
    [setDock, pid],
  )

  return (
    <div className="wb-editor">
      <DockviewReact
        theme={THEME}
        components={{ editor: EditorHost }}
        tabComponents={{ editorTab: EditorTab }}
        defaultTabComponent={EditorTab}
        watermarkComponent={Watermark}
        onReady={onReady}
      />
    </div>
  )
}
