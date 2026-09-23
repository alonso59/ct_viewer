// Editor area on dockview (UI-03): tabs, preview mode, drag, split; tabs persist per project (FE-04).
import {
  DockviewReact,
  type DockviewReadyEvent,
  type IDockviewPanelHeaderProps,
  type IDockviewPanelProps,
} from 'dockview-react'
import { Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router'

import { Icon, codicon } from '../theme'
import { registry } from './registry'
import { openEditor, pinEditor, useWorkbench, type EditorParams } from './workbenchStore'

const THEME = { name: 'rw', className: 'dockview-theme-dark dv-rw', gap: 0 }
const tabsKey = (pid: string) => `rw.tabs.${pid}`

function EditorHost(props: IDockviewPanelProps<EditorParams>) {
  const { t } = useTranslation()
  const [active, setActive] = useState(props.api.isActive)
  useEffect(() => {
    const d = props.api.onDidActiveChange((e) => setActive(e.isActive))
    return () => d.dispose()
  }, [props.api])
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

function matchLocation(pid: string, pathname: string, search: string): EditorParams | null {
  const rest = pathname.slice(`/p/${pid}`.length) || '/'
  const sp = new URLSearchParams(search)
  for (const e of registry.editors.values()) {
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

  const onReady = (e: DockviewReadyEvent) => {
    setDock(e.api)
    try {
      const saved = localStorage.getItem(tabsKey(pid))
      if (saved) e.api.fromJSON(JSON.parse(saved))
    } catch {
      e.api.clear()
    }
    e.api.onDidLayoutChange(() => {
      try {
        localStorage.setItem(tabsKey(pid), JSON.stringify(e.api.toJSON()))
      } catch {
        // storage unavailable
      }
    })
    e.api.onDidActivePanelChange(({ panel }) => setActive((panel?.params as EditorParams | undefined) ?? null))
    const initial = matchLocation(pid, location.pathname, location.search)
    if (initial) {
      const { type, ...params } = initial
      openEditor(type, params)
    } else if (e.api.activePanel) {
      setActive(e.api.activePanel.params as EditorParams)
    }
    ready.current = true
  }

  // Deep links and history navigation open the matching editor
  useEffect(() => {
    if (!ready.current) return
    const path = location.pathname + location.search
    if (path === lastPath.current) return
    const m = matchLocation(pid, location.pathname, location.search)
    if (m) {
      lastPath.current = path
      const { type, ...params } = m
      openEditor(type, params)
    }
  }, [location.pathname, location.search, pid])

  // The active editor drives the URL (FE-04)
  const active = useWorkbench((s) => s.active)
  const urlToken = useWorkbench((s) => s.urlToken)
  useEffect(() => {
    if (!ready.current) return
    const path = pathFor(pid, active)
    if (path !== lastPath.current) {
      lastPath.current = path
      navigate(path, { replace: true })
    }
  }, [active, urlToken, pid, navigate])

  useEffect(() => () => setDock(null), [setDock])

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
