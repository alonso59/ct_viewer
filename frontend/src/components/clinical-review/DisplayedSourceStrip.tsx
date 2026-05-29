import { Chip, Paper, Stack, Typography } from '@mui/material'

import type { Axis, CanonicalPhase, Scope } from '../../services/api'

interface DisplayedSourceStripProps {
  focusedPlane: Axis
  overlayEnabled: boolean
  scanIdx: string | null
  scope: Scope
  selectedPhase: CanonicalPhase | null
  selectedWarningCount: number
  side: string | null
  sourceLabel: string
  volumeLoading: boolean
}

function DisplayedSourceStrip({
  focusedPlane,
  overlayEnabled,
  scanIdx,
  scope,
  selectedPhase,
  selectedWarningCount,
  side,
  sourceLabel,
  volumeLoading,
}: DisplayedSourceStripProps) {
  return (
    <Paper
      elevation={0}
      data-testid="displayed-source-strip"
      sx={{
        px: 1.25,
        py: 0.85,
        borderColor: scope === 'voi' ? 'success.dark' : 'primary.dark',
        backgroundColor:
          scope === 'voi' ? 'rgba(34, 197, 94, 0.08)' : 'rgba(125, 211, 252, 0.08)',
      }}
    >
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={0.9}
        alignItems={{ md: 'center' }}
        justifyContent="space-between"
      >
        <Stack spacing={0.2} sx={{ minWidth: 0 }}>
          <Typography variant="caption" color="text.secondary">
            Displayed source
          </Typography>
          <Typography
            variant="body2"
            fontWeight={800}
            sx={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {sourceLabel}
          </Typography>
        </Stack>
        <Stack direction="row" spacing={0.6} flexWrap="wrap" useFlexGap>
          <Chip label={`Phase ${selectedPhase ?? '-'}`} color="primary" size="small" />
          <Chip
            label={scope === 'voi' ? 'VOI' : 'Complete CT'}
            color={scope === 'voi' ? 'success' : 'primary'}
            size="small"
            variant="filled"
          />
          <Chip label={`Focus ${focusedPlane}`} size="small" variant="outlined" />
          <Chip label={`Scan ${scanIdx || '-'}`} size="small" variant="outlined" />
          {side ? <Chip label={`Side ${side}`} size="small" variant="outlined" /> : null}
          <Chip
            label={`Overlay ${overlayEnabled ? 'on' : 'off'}`}
            color={overlayEnabled ? 'success' : 'default'}
            size="small"
            variant={overlayEnabled ? 'filled' : 'outlined'}
          />
          <Chip
            label={selectedWarningCount > 0 ? `${selectedWarningCount} source warnings` : 'No source warnings'}
            color={selectedWarningCount > 0 ? 'warning' : 'default'}
            size="small"
            variant={selectedWarningCount > 0 ? 'filled' : 'outlined'}
          />
          {volumeLoading ? <Chip label="Loading image" size="small" variant="outlined" /> : null}
        </Stack>
      </Stack>
    </Paper>
  )
}

export default DisplayedSourceStrip
