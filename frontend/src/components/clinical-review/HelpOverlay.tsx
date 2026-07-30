import { Chip, Dialog, DialogContent, DialogTitle, Stack, Typography } from '@mui/material'

interface HelpOverlayProps {
  open: boolean
  onClose: () => void
}

const shortcuts = [
  ['N', 'Load next case'],
  ['A', 'Accept case'],
  ['C', 'Needs correction'],
  ['R', 'Reject case'],
  ['Space', 'Next slice'],
  ['Ctrl + wheel', 'Zoom active panel'],
  ['Shift + drag', 'Pan active panel'],
  ['Right drag', 'Window / level'],
] as const

function HelpOverlay({ open, onClose }: HelpOverlayProps) {
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm" data-testid="help-overlay">
      <DialogTitle>Review shortcuts</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={1}>
          {shortcuts.map(([keyName, behavior]) => (
            <Stack key={keyName} direction="row" spacing={1} alignItems="center" justifyContent="space-between">
              <Chip label={keyName} size="small" variant="outlined" />
              <Typography variant="body2">{behavior}</Typography>
            </Stack>
          ))}
        </Stack>
      </DialogContent>
    </Dialog>
  )
}

export default HelpOverlay
