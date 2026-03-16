import { Slider, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'

import type { Axis } from '../../services/api'

interface SliceSliderProps {
  axis: Axis
  color: string
  index: number
  maxIndex: number
  onChange: (value: number) => void
}

function SliceSlider({
  axis,
  color,
  index,
  maxIndex,
  onChange,
}: SliceSliderProps) {
  const boundedIndex = Math.min(index, Math.max(0, maxIndex))
  const [draftIndex, setDraftIndex] = useState(boundedIndex)

  useEffect(() => {
    setDraftIndex(boundedIndex)
  }, [boundedIndex])

  return (
    <Stack spacing={0.75}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase' }}>
          {axis}
        </Typography>
        <Typography variant="caption" sx={{ color }}>
          {index + 1} / {maxIndex + 1}
        </Typography>
      </Stack>
      <Slider
        size="small"
        min={0}
        max={Math.max(0, maxIndex)}
        value={draftIndex}
        onChange={(_event, value) => setDraftIndex(value as number)}
        onChangeCommitted={(_event, value) => {
          const nextValue = value as number
          setDraftIndex(nextValue)
          onChange(nextValue)
        }}
        sx={{
          color,
          py: 0,
        }}
      />
    </Stack>
  )
}

export default SliceSlider
