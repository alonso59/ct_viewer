import * as RTooltip from '@radix-ui/react-tooltip'
import { useEffect, type ReactNode } from 'react'

import { useLayout } from '../state'
import { ActivityBar } from './ActivityBar'
import { CommandPalette } from './CommandPalette'
import { EditorArea } from './EditorArea'
import { Inspector } from './Inspector'
import { Panel, PanelContentWatch } from './Panel'
import { ReviewerPrompt } from './ReviewerPrompt'
import { SideBar } from './SideBar'
import { StatusBar } from './StatusBar'
import { TitleBar } from './TitleBar'
import { registry } from './registry'
import { Toasts } from './Toasts'
import { ToolBar } from './ToolBar'
import { useWorkbench } from './workbenchStore'
import './shell.css'

/** The workbench shell for one project (UI-01). Domain content comes only from the registry. */
export function Workbench({ pid, brand, share }: { pid: string; brand: ReactNode; share?: ReactNode }) {
  const load = useLayout((s) => s.load)
  const loadedPid = useLayout((s) => s.pid)
  useEffect(() => {
    load(pid)
    useWorkbench.setState({ pid })
    // Leaving the project (e.g. browser Back to the home, AUD-A1-02) leaves no stale project behind
    return () => useWorkbench.setState({ pid: null, active: null })
  }, [pid, load])
  // UI-13 (AUD-A1-18): the bottom panel follows the active editor type
  const editorType = useWorkbench((s) => s.active?.type ?? null)
  useEffect(() => {
    if (loadedPid === pid) useLayout.getState().setEditorType(editorType)
  }, [editorType, loadedPid, pid])
  if (loadedPid !== pid) return null
  return (
    <div className="wb">
      <TitleBar brand={brand} share={share} />
      <ToolBar />
      <div className="wb-main">
        <ActivityBar />
        <SideBar />
        <div className="wb-center">
          <EditorArea key={pid} pid={pid} />
          <Panel />
          <PanelContentWatch />
        </div>
        <Inspector />
      </div>
      <StatusBar />
      <ShellOverlays />
    </div>
  )
}

/** Overlays shared by every page (also the workspace home and Open mode): the palette and its
 *  keys work on every route (AUD-A1-01) */
export function ShellOverlays() {
  return (
    <>
      <CommandPalette />
      <Toasts />
      <ReviewerPrompt />
      {registry.overlays.filter((o) => registry.allowed(o)).map(({ id, component: C }) => <C key={id} />)}
    </>
  )
}

export function ShellProviders({ children }: { children: ReactNode }) {
  return <RTooltip.Provider delayDuration={450}>{children}</RTooltip.Provider>
}
