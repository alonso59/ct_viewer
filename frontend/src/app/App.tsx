import { QueryClientProvider } from '@tanstack/react-query'
import { useEffect } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'

import { queryClient } from '../api'
import { WorkspaceHome } from '../features/projects'
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

function Keys() {
  useGlobalKeybindings()
  return null
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ShellProviders>
        <BrowserRouter>
          <Theme />
          <Keys />
          <Routes>
            <Route path="/" element={<><WorkspaceHome /><ShellOverlays /></>} />
            <Route path="/p/:pid/*" element={<ProjectRoute />} />
          </Routes>
        </BrowserRouter>
      </ShellProviders>
    </QueryClientProvider>
  )
}
