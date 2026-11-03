import * as RTooltip from '@radix-ui/react-tooltip'
import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Announcer } from '../lib/announce'
import { ErrorBoundary } from '../lib/ErrorBoundary'
import { useLayout } from '../state'
import { ActivityBar } from './ActivityBar'
import { CommandPalette } from './CommandPalette'
import { Inspector } from './Inspector'
import { Panel, PanelContentWatch } from './Panel'
import { ReviewerPrompt } from './ReviewerPrompt'
import { SideBar } from './SideBar'
import { StatusBar } from './StatusBar'
import { TitleBar } from './TitleBar'
import { EDITOR_REGION_ID } from './regions'
import { registry } from './registry'
import { Toasts } from './Toasts'
import { ToolBar } from './ToolBar'
import { useWorkbench } from './workbenchStore'
import './shell.css'

// dockview (the editor area) loads with the first project workbench, not with the home
const EditorArea = lazy(() => import('./EditorArea').then((m) => ({ default: m.EditorArea })))

/** The workbench shell for one project. Domain content comes only from the registry. */
export function Workbench({ pid, brand, share }: { pid: string; brand: ReactNode; share?: ReactNode }) {
  const { t } = useTranslation()
  const load = useLayout((s) => s.load)
  const loadedPid = useLayout((s) => s.pid)
  useEffect(() => {
    load(pid)
    useWorkbench.setState({ pid })
    // Leaving the project (e.g. browser Back to the home) leaves no stale project behind
    return () => useWorkbench.setState({ pid: null, active: null })
  }, [pid, load])
  // The bottom panel follows the active editor type
  const editorType = useWorkbench((s) => s.active?.type ?? null)
  useEffect(() => {
    if (loadedPid === pid) useLayout.getState().setEditorType(editorType)
  }, [editorType, loadedPid, pid])
  if (loadedPid !== pid) return null
  return (
    <div className="wb">
      {/* the first Tab stop; it moves focus without touching the URL */}
      <a
        className="skip-link"
        href={`#${EDITOR_REGION_ID}`}
        onClick={(e) => {
          e.preventDefault()
          document.getElementById(EDITOR_REGION_ID)?.focus()
        }}
      >
        {t('shell.skipToEditor')}
      </a>
      <TitleBar brand={brand} share={share} />
      <ToolBar />
      <div className="wb-main">
        <ActivityBar />
        <ErrorBoundary><SideBar /></ErrorBoundary>
        <div className="wb-center">
          <main id={EDITOR_REGION_ID} className="wb-editor-region" tabIndex={-1} aria-label={t('shell.editorArea')}>
            <ErrorBoundary>
              <Suspense fallback={<div className="wb-editor" />}>
                <EditorArea key={pid} pid={pid} />
              </Suspense>
            </ErrorBoundary>
          </main>
          <ErrorBoundary><Panel /></ErrorBoundary>
          <PanelContentWatch />
        </div>
        <ErrorBoundary><Inspector /></ErrorBoundary>
      </div>
      <StatusBar />
      <ShellOverlays />
    </div>
  )
}

/** Overlays shared by every page (also the workspace home and Open mode): the palette and its
 *  keys work on every route */
export function ShellOverlays() {
  return (
    <>
      <CommandPalette />
      <Toasts />
      <Announcer />
      <ReviewerPrompt />
      {registry.overlays.filter((o) => registry.allowed(o)).map(({ id, component: C }) => <C key={id} />)}
    </>
  )
}

export function ShellProviders({ children }: { children: ReactNode }) {
  return <RTooltip.Provider delayDuration={450}>{children}</RTooltip.Provider>
}
