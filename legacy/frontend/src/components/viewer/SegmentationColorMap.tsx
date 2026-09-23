import { Box, Stack, Typography } from '@mui/material'

import {
  getSegmentationColor,
  getSegmentationLabel,
  isBaseSegmentationLabel,
  sortedLayerLabels,
} from './segmentationPalette'

interface SegmentationColorMapProps {
  labels: number[]
}

function SegmentationColorMap({ labels }: SegmentationColorMapProps) {
  const genericLabels = sortedLayerLabels(labels).filter((label) => !isBaseSegmentationLabel(label))

  if (genericLabels.length === 0) {
    return null
  }

  return (
    <Stack spacing={0.75} data-segmentation-cmap>
      <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: '0.16em' }}>
        Cmap palette
      </Typography>
      <Stack direction="row" spacing={0.9} flexWrap="wrap" useFlexGap>
        {genericLabels.map((label) => {
          const color = getSegmentationColor(label)
          return (
            <Stack
              key={label}
              direction="row"
              spacing={0.65}
              alignItems="center"
              data-cmap-label={label}
              sx={{ minHeight: 24, minWidth: 0 }}
            >
              <Box
                sx={{
                  width: 12,
                  height: 12,
                  borderRadius: '50%',
                  backgroundColor: color,
                  border: '1px solid rgba(255,255,255,0.28)',
                  boxShadow: '0 0 0 1px rgba(0,0,0,0.12)',
                  flex: '0 0 auto',
                }}
              />
              <Typography variant="caption" color="text.primary">
                {getSegmentationLabel(label)}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                {color}
              </Typography>
            </Stack>
          )
        })}
      </Stack>
    </Stack>
  )
}

export default SegmentationColorMap
