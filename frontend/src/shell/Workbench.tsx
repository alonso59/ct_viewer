import * as RTooltip from '@radix-ui/react-tooltip'
import { useEffect, type ReactNode } from 'react'

import { useLayout } from '../state'
import { ActivityBar } from './ActivityBar'
import { CommandPalette } from './CommandPalette'
import { EditorArea } from './EditorArea'
import { Inspector } from './Inspector'
import { Panel } from './Panel'
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
export function Workbench({ pid, brand, shareUrl }: { pid: string; brand: ReactNode; shareUrl?: string }) {
  const load = useLayout((s) => s.load)
  const loadedPid = useLayout((s) => s.pid)
  useEffect(() => {
    load(pid)
    useWorkbench.setState({ pid })
  }, [pid, load])
  if (loadedPid !== pid) return null
  return (
    <div className="wb">
      <TitleBar brand={brand} shareUrl={shareUrl} />
      <ToolBar />
      <div className="wb-main">
        <ActivityBar />
        <SideBar />
        <div className="wb-center">
          <EditorArea key={pid} pid={pid} />
          <Panel />
        </div>
        <Inspector />
      </div>
      <StatusBar />
      <CommandPalette />
      <ShellOverlays />
    </div>
  )
}

/** Overlays shared by every page (also the workspace home) */
export function ShellOverlays() {
  return (
    <>
      <Toasts />
      <ReviewerPrompt />
      {registry.overlays.filter((o) => registry.allowed(o)).map(({ id, component: C }) => <C key={id} />)}
    </>
  )
}

export function ShellProviders({ children }: { children: ReactNode }) {
  return <RTooltip.Provider delayDuration={450}>{children}</RTooltip.Provider>
}
