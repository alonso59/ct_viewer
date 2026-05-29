import { Suspense, lazy, useEffect, useState } from 'react'
import {
  AppBar,
  Box,
  Button,
  Chip,
  Container,
  Stack,
  Toolbar,
  Typography,
} from '@mui/material'
import {
  Link as RouterLink,
  matchPath,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom'

import LoginDialog from './components/LoginDialog'
import { useWorkspace } from './hooks/useWorkspace'
import DatasetSelectorPage from './pages/DatasetSelectorPage'
import {
  apiClient,
  getStoredAuthToken,
  registerAuthPromptHandler,
} from './services/api'

type ApiStatus = 'checking' | 'online' | 'offline'

const PatientListPage = lazy(() => import('./pages/PatientListPage'))
const ViewerPage = lazy(() => import('./pages/ViewerPage'))
const MainReviewScreen = lazy(() => import('./pages/MainReviewScreen'))

function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')
  const [loginOpen, setLoginOpen] = useState(false)
  const [storedToken, setStoredToken] = useState(getStoredAuthToken())
  const [resolveToken, setResolveToken] = useState<((token: string | null) => void) | null>(
    null,
  )
  const workspaceState = useWorkspace()
  const activeDatasetId = workspaceState.workspace.dataset_id
  const isMainReviewRoute = Boolean(
    matchPath('/datasets/:dsid/review', location.pathname) ??
      matchPath('/datasets/:dsid/review/:caseId', location.pathname),
  )
  const isViewerRoute =
    isMainReviewRoute || Boolean(matchPath('/datasets/:dsid/patients/:pid/viewer', location.pathname))

  useEffect(() => {
    let active = true

    async function checkApiHealth() {
      try {
        await apiClient.getHealth()
        if (active) {
          setApiStatus('online')
        }
      } catch {
        if (active) {
          setApiStatus('offline')
        }
      }
    }

    void checkApiHealth()

    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (apiStatus !== 'offline') {
      return
    }

    let active = true
    const interval = window.setInterval(() => {
      apiClient
        .getHealth()
        .then(() => {
          if (active) {
            setApiStatus('online')
          }
        })
        .catch(() => {
          if (active) {
            setApiStatus('offline')
          }
        })
    }, 15000)

    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [apiStatus])

  useEffect(() => {
    registerAuthPromptHandler(
      () =>
        new Promise((resolve) => {
          setStoredToken(getStoredAuthToken())
          setResolveToken(() => resolve)
          setLoginOpen(true)
        }),
    )

    return () => {
      registerAuthPromptHandler(null)
    }
  }, [])

  function closeLoginDialog(nextToken: string | null) {
    setLoginOpen(false)
    if (resolveToken) {
      resolveToken(nextToken)
      setResolveToken(null)
    }
  }

  useEffect(() => {
    if (workspaceState.loading || workspaceState.workspace.configured) {
      return
    }
    if (location.pathname !== '/') {
      navigate('/', { replace: true })
    }
  }, [
    location.pathname,
    navigate,
    workspaceState.loading,
    workspaceState.workspace.configured,
  ])

  const routes = (
    <Suspense
      fallback={
        <Stack spacing={1.25} alignItems="center" justifyContent="center" sx={{ minHeight: 240 }}>
          <Typography variant="body2" color="text.secondary">
            Loading page...
          </Typography>
        </Stack>
      }
    >
      <Routes>
        <Route
          path="/"
          element={
            <DatasetSelectorPage
              workspace={workspaceState.workspace}
              workspaceLoading={workspaceState.loading}
              workspaceError={workspaceState.error}
              onWorkspaceChange={(workspace) => workspaceState.setWorkspace(workspace)}
            />
          }
        />
        <Route path="/datasets/:dsid/review" element={<MainReviewScreen />} />
        <Route
          path="/datasets/:dsid/review/:caseId"
          element={<MainReviewScreen />}
        />
        <Route path="/datasets/:dsid/cases" element={<LegacyCasesRedirect />} />
        <Route
          path="/datasets/:dsid/cases/:caseId/review"
          element={<LegacyCaseReviewRedirect />}
        />
        <Route path="/datasets/:dsid/cases/:caseId/dossier" element={<LegacyCaseReviewRedirect />} />
        <Route path="/datasets/:dsid/patients" element={<PatientListPage />} />
        <Route
          path="/datasets/:dsid/patients/:pid/viewer"
          element={<ViewerPage />}
        />
      </Routes>
    </Suspense>
  )

  return (
    <Box sx={{ minHeight: '100vh' }}>
      {!isMainReviewRoute ? (
        <AppBar
          position="sticky"
          elevation={0}
          sx={{
            borderBottom: '1px solid',
            borderColor: 'divider',
            backgroundColor: 'rgba(18, 18, 18, 0.82)',
            backdropFilter: 'blur(18px)',
          }}
        >
          <Toolbar sx={{ gap: 2, flexWrap: 'wrap', py: 1 }}>
            <Box sx={{ flexGrow: 1 }}>
              <Typography variant="overline" color="text.secondary">
                ccRCC CT Dataset Curation
              </Typography>
              <Typography variant="h6">Medical Review Workspace</Typography>
            </Box>

            <Stack direction="row" spacing={1.25} flexWrap="wrap" useFlexGap>
              <Button component={RouterLink} to="/" color="inherit">
                Dataset
              </Button>
              {activeDatasetId ? (
                <Button
                  component={RouterLink}
                  to={`/datasets/${activeDatasetId}/review`}
                  color="inherit"
                >
                  Review
                </Button>
              ) : null}
            </Stack>

            <Chip
              color={
                apiStatus === 'online'
                  ? 'primary'
                  : apiStatus === 'offline'
                    ? 'secondary'
                    : 'default'
              }
              label={
                apiStatus === 'online'
                  ? 'API online'
                  : apiStatus === 'offline'
                    ? 'API unreachable'
                    : 'Checking API'
              }
              variant={apiStatus === 'checking' ? 'outlined' : 'filled'}
            />
          </Toolbar>
        </AppBar>
      ) : null}

      {isMainReviewRoute ? (
        routes
      ) : isViewerRoute ? (
        <Box
          sx={{
            width: '100%',
            px: { xs: 2, sm: 2.5, md: 3, xl: 4 },
            py: { xs: 2, md: 2.5 },
          }}
        >
          {routes}
        </Box>
      ) : (
        <Container maxWidth="lg" sx={{ py: { xs: 3, md: 5 } }}>
          {routes}
        </Container>
      )}

      <LoginDialog
        key={`${Number(loginOpen)}:${storedToken}`}
        open={loginOpen}
        initialToken={storedToken}
        onCancel={() => closeLoginDialog(null)}
        onSubmit={(token) => closeLoginDialog(token)}
      />
    </Box>
  )
}

function LegacyCasesRedirect() {
  const { dsid = '' } = useParams<{ dsid: string }>()
  return <Navigate to={`/datasets/${dsid}/review`} replace />
}

function LegacyCaseReviewRedirect() {
  const { dsid = '', caseId = '' } = useParams<{ dsid: string; caseId: string }>()
  return <Navigate to={`/datasets/${dsid}/review/${caseId}`} replace />
}

export default App
