// Viewer harness entry (manual P3 testing, TST-09 bench). Not part of the app bundle.
import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '../../../theme'
import '../../../i18n'
import { queryClient } from '../../../api'
import { ShellProviders } from '../../../shell'
import { Harness } from './Harness'

const root = document.getElementById('root')
if (!root) throw new Error('Missing #root element')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ShellProviders>
        <Harness />
      </ShellProviders>
    </QueryClientProvider>
  </StrictMode>,
)
