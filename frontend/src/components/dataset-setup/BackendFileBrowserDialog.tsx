import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material'

import {
  apiClient,
  getApiErrorMessage,
  type DatasetBrowserEntry,
  type DatasetBrowserRoot,
} from '../../services/api'

interface BackendFileBrowserDialogProps {
  open: boolean
  initialPath?: string
  onClose: () => void
  onSelect: (path: string) => void
}

function BackendFileBrowserDialog({
  open,
  initialPath,
  onClose,
  onSelect,
}: BackendFileBrowserDialogProps) {
  const [currentPath, setCurrentPath] = useState('')
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [entries, setEntries] = useState<DatasetBrowserEntry[]>([])
  const [quickAccess, setQuickAccess] = useState<DatasetBrowserRoot[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      return
    }
    let active = true
    async function initialize() {
      let startPath = initialPath || ''
      try {
        const response = await apiClient.listDatasetBrowserRoots()
        if (!active) return
        const roots = response.roots.filter((r) => r.exists && r.readable)
        setQuickAccess(roots)
        if (!startPath) {
          const home = roots.find((r) => r.source === 'home')
          startPath = home?.path || '/'
        }
      } catch {
        if (!active) return
      }
      void loadPath(startPath || '/')
    }
    void initialize()
    return () => { active = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialPath])

  async function loadPath(path: string) {
    setLoading(true)
    setError(null)
    try {
      const response = await apiClient.listDatasetBrowserPath(path)
      setCurrentPath(response.path)
      setParentPath(response.parent_path)
      setEntries(response.entries)
    } catch (requestError) {
      setError(getApiErrorMessage(requestError))
      setEntries([])
    } finally {
      setLoading(false)
    }
  }

  const breadcrumbs = useMemo(() => buildBreadcrumbs(currentPath), [currentPath])

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Browse Dataset Folder</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          {error ? <Alert severity="error">{error}</Alert> : null}

          {quickAccess.length > 0 ? (
            <Stack spacing={0.5}>
              <Typography variant="caption" color="text.secondary">
                Quick access
              </Typography>
              <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                {quickAccess.map((root) => (
                  <Chip
                    key={root.path}
                    label={root.label}
                    size="small"
                    variant={root.path === currentPath ? 'filled' : 'outlined'}
                    color="primary"
                    onClick={() => void loadPath(root.path)}
                  />
                ))}
              </Stack>
            </Stack>
          ) : null}

          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            {breadcrumbs.map((crumb) => (
              <Chip
                key={crumb.path}
                label={crumb.label}
                size="small"
                variant={crumb.path === currentPath ? 'filled' : 'outlined'}
                onClick={() => void loadPath(crumb.path)}
              />
            ))}
          </Stack>

          <Box
            sx={{
              border: '1px solid',
              borderColor: 'divider',
              minHeight: 300,
              maxHeight: 420,
              overflow: 'auto',
              backgroundColor: 'rgba(0, 0, 0, 0.24)',
            }}
          >
            {loading ? <LinearProgress /> : null}
            <List dense disablePadding>
              {parentPath ? (
                <ListItemButton onClick={() => void loadPath(parentPath)}>
                  <ListItemText primary=".." secondary="Parent folder" />
                </ListItemButton>
              ) : null}
              {entries.map((entry) => (
                <ListItemButton
                  key={entry.path}
                  disabled={!entry.readable || entry.type === 'file'}
                  onClick={() => entry.type === 'directory' && void loadPath(entry.path)}
                >
                  <ListItemText
                    primary={
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Typography variant="body2">{entry.name}</Typography>
                        {entry.maybe_has_dataset_structure ? (
                          <Chip label="dataset-like" size="small" color="primary" variant="outlined" />
                        ) : null}
                      </Stack>
                    }
                    secondary="Folder"
                  />
                </ListItemButton>
              ))}
            </List>
          </Box>

          <Typography variant="caption" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
            {currentPath || '—'}
          </Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!currentPath || loading}
          onClick={() => onSelect(currentPath)}
        >
          Select Folder
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function buildBreadcrumbs(currentPath: string) {
  if (!currentPath) return []
  const normalized = currentPath.replace(/\/+$/, '') || '/'
  const parts = normalized.split('/').filter(Boolean)
  const crumbs = [{ label: '/', path: '/' }]
  let built = ''
  for (const part of parts) {
    built = `${built}/${part}`
    crumbs.push({ label: part, path: built })
  }
  return crumbs
}

export default BackendFileBrowserDialog
