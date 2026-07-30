import { Slider, Stack, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

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
  const rootRef = useRef<HTMLDivElement | null>(null)
  const boundedIndexRef = useRef(boundedIndex)
  const maxIndexRef = useRef(maxIndex)
  const onChangeRef = useRef(onChange)

  useEffect(() => {
    setDraftIndex(boundedIndex)
  }, [boundedIndex])

  useEffect(() => {
    boundedIndexRef.current = boundedIndex
  }, [boundedIndex])

  useEffect(() => {
    maxIndexRef.current = maxIndex
  }, [maxIndex])

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  useEffect(() => {
    const element = rootRef.current
    if (!element) {
      return
    }

    function handleNativeWheel(event: WheelEvent) {
      event.preventDefault()
      event.stopPropagation()

      if (event.deltaY === 0) {
        return
      }

      const max = Math.max(0, maxIndexRef.current)
      if (max <= 0) {
        return
      }

      const current = Math.min(boundedIndexRef.current, max)
      const nextValue = Math.min(max, Math.max(0, current + (event.deltaY > 0 ? 1 : -1)))
      if (nextValue === current) {
        return
      }

      boundedIndexRef.current = nextValue
      setDraftIndex(nextValue)
      onChangeRef.current(nextValue)
    }

    element.addEventListener('wheel', handleNativeWheel, { passive: false })
    return () => {
      element.removeEventListener('wheel', handleNativeWheel)
    }
  }, [])

  return (
    <Stack ref={rootRef} spacing={0.75} sx={{ overscrollBehavior: 'contain' }}>
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
