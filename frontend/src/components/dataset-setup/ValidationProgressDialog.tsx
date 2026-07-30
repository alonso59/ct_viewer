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
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material'

import type {
  SelectionValidationMessage,
  WorkspaceSelectionValidationResponse,
} from '../../services/api'

interface ValidationProgressDialogProps {
  open: boolean
  progress: number
  currentStep: string
  result: WorkspaceSelectionValidationResponse | null
  error: string | null
  onClose: () => void
}

function ValidationProgressDialog({
  open,
  progress,
  currentStep,
  result,
  error,
  onClose,
}: ValidationProgressDialogProps) {
  const finished = Boolean(result || error)
  const hasBlockingErrors = (result?.errors.length ?? 0) > 0 || Boolean(error)
  const barColor = finished && !hasBlockingErrors ? 'success' : hasBlockingErrors ? 'error' : 'primary'

  return (
    <Dialog open={open} fullWidth maxWidth="sm">
      <DialogTitle>Validating Dataset Selection</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2.25}>
          <Box>
            <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
              <Typography variant="body2">{currentStep}</Typography>
              <Typography variant="body2" color="text.secondary">
                {Math.round(progress)}%
              </Typography>
            </Stack>
            <LinearProgress color={barColor} variant="determinate" value={progress} />
          </Box>

          {error ? <Alert severity="error">{error}</Alert> : null}

          {result ? (
            <Stack spacing={1.5}>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip color="success" label={`Success ${result.successes.length}`} />
                <Chip
                  color={result.warnings.length > 0 ? 'warning' : 'default'}
                  label={`Warnings ${result.warnings.length}`}
                  variant={result.warnings.length > 0 ? 'filled' : 'outlined'}
                />
                <Chip
                  color={result.errors.length > 0 ? 'error' : 'default'}
                  label={`Errors ${result.errors.length}`}
                  variant={result.errors.length > 0 ? 'filled' : 'outlined'}
                />
              </Stack>

              <Box
                sx={{
                  border: '1px solid',
                  borderColor: 'divider',
                  p: 1.5,
                  backgroundColor: 'rgba(0, 0, 0, 0.22)',
                }}
              >
                <Stack spacing={0.5}>
                  <Typography variant="body2">
                    Dataset root: {result.summary.dataset_root ?? 'Not resolved'}
                  </Typography>
                  <Typography variant="body2">
                    database.csv: {result.summary.database_csv_path ?? 'Not found'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {result.summary.row_count} rows, {result.summary.case_count} cases,
                    sampled {result.summary.sampled_referenced_files} referenced paths.
                  </Typography>
                </Stack>
              </Box>

              <MessageGroup title="Errors" messages={result.errors} severity="error" />
              <MessageGroup title="Warnings" messages={result.warnings} severity="warning" />
              <MessageGroup title="Successes" messages={result.successes.slice(0, 6)} severity="success" />
            </Stack>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={!finished}>
          OK
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function MessageGroup({
  title,
  messages,
  severity,
}: {
  title: string
  messages: SelectionValidationMessage[]
  severity: 'success' | 'warning' | 'error'
}) {
  if (messages.length === 0) {
    return null
  }
  return (
    <Box>
      <Typography variant="overline" color={`${severity}.main`}>
        {title}
      </Typography>
      <List dense disablePadding>
        {messages.map((message, index) => (
          <ListItem key={`${message.code}-${index}`} disableGutters sx={{ py: 0.25 }}>
            <ListItemText
              primary={message.message}
              secondary={message.path ?? undefined}
              primaryTypographyProps={{ variant: 'body2' }}
              secondaryTypographyProps={{ sx: { wordBreak: 'break-all' } }}
            />
          </ListItem>
        ))}
      </List>
    </Box>
  )
}

export default ValidationProgressDialog
