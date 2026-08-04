import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { CssBaseline, ThemeProvider } from '@mui/material'
import { BrowserRouter } from './services/router'
import './index.css'
import App from './App.tsx'
import {
  initializeDesktopRuntime,
  notifyDesktopFrontendReady,
} from './services/desktop'
import { theme } from './styles/theme'

async function bootstrap() {
  await initializeDesktopRuntime()

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </StrictMode>,
  )

  await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()))
  await notifyDesktopFrontendReady()
}

void bootstrap()
