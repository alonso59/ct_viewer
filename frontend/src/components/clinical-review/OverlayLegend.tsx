import { Box, Chip, Stack, Typography } from '@mui/material'

import { LAYER_META } from './reviewUi'

interface OverlayLegendProps {
  mode: 'filled' | 'contour'
  visibleLabels: number[]
}

function OverlayLegend({ mode, visibleLabels }: OverlayLegendProps) {
  return (
    <Box
      data-testid="overlay-legend"
      sx={{
        position: 'absolute',
        left: 8,
        top: 8,
        zIndex: 5,
        px: 0.8,
        py: 0.65,
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        backgroundColor: 'rgba(0,0,0,0.58)',
        backdropFilter: 'blur(8px)',
        pointerEvents: 'none',
      }}
    >
      <Stack spacing={0.45}>
        <Typography variant="caption" color="text.secondary">
          Overlay {mode}
        </Typography>
        <Stack direction="row" spacing={0.45} flexWrap="wrap" useFlexGap>
          {[1, 2, 3].map((label) => (
            <Chip
              key={label}
              label={LAYER_META[label].label}
              size="small"
              variant={visibleLabels.includes(label) ? 'filled' : 'outlined'}
              sx={{
                height: 20,
                opacity: visibleLabels.includes(label) ? 1 : 0.45,
                borderColor: LAYER_META[label].color,
                color: visibleLabels.includes(label) ? '#050505' : LAYER_META[label].color,
                backgroundColor: visibleLabels.includes(label) ? LAYER_META[label].color : 'transparent',
                '& .MuiChip-label': { px: 0.8 },
              }}
            />
          ))}
        </Stack>
      </Stack>
    </Box>
  )
}

export default OverlayLegend
