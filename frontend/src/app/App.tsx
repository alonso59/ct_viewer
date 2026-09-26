import { QueryClientProvider } from '@tanstack/react-query'
import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router'

import { queryClient, useHealth, viewPid } from '../api'
import { OpenDialogHost, OpenRoute } from '../features/open'
import { WorkspaceHome } from '../features/projects'
import { configureViewer } from '../features/viewer'
import { ShellOverlays, ShellProviders, useGlobalKeybindings } from '../shell'
import { useSettings } from '../state'
import { applyTheme } from '../theme'
import { bootstrap } from './bootstrap'
import { ProjectRoute } from './ProjectRoute'

bootstrap()

function Theme() {
  const theme = useSettings((s) => s.theme)
  useEffect(() => {
    applyTheme(theme)
    if (theme !== 'system') return
    const mq = window.matchMedia?.('(prefers-color-scheme: light)')
    const on = () => applyTheme('system')
    mq?.addEventListener('change', on)
    return () => mq?.removeEventListener('change', on)
  }, [theme])
  return null
}

/** VW-14: loaded-tab budget from the server's UI runtime config (API-01). */
function ViewerConfig() {
  const maxLoaded = useHealth().data?.ui_config.viewer_max_loaded
  useEffect(() => {
    if (maxLoaded) configureViewer({ maxLoaded })
  }, [maxLoaded])
  return null
}

function Keys() {
  useGlobalKeybindings()
  return null
}

/** PRJ-17: `/v/{token}` is the view-only workbench of pseudo project `view-{token}`; a deep link
 *  (`/v/{token}/case/…`, AUD-A1-11) keeps its tab */
function ViewLink() {
  const { token = '', '*': rest = '' } = useParams()
  return <Navigate to={`/p/${viewPid(token)}${rest ? `/${rest}` : ''}${location.search}`} replace />
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ShellProviders>
        <BrowserRouter>
          <Theme />
          <Keys />
          <ViewerConfig />
          <OpenDialogHost />
          <Routes>
            <Route path="/" element={<><WorkspaceHome /><ShellOverlays /></>} />
            <Route path="/open" element={<><OpenRoute /><ShellOverlays /></>} />
            <Route path="/open/:sid" element={<><OpenRoute /><ShellOverlays /></>} />
            <Route path="/v/:token/*" element={<ViewLink />} />
            <Route path="/p/:pid/*" element={<ProjectRoute />} />
          </Routes>
        </BrowserRouter>
      </ShellProviders>
    </QueryClientProvider>
  )
}
