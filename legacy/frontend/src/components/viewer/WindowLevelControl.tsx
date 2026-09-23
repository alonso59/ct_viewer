import { Button, Chip, Stack, TextField, Typography } from '@mui/material'
import { useEffect, useState } from 'react'

import { WINDOW_LEVEL_PRESETS, type WindowLevelMode, type WindowLevelPreset } from './useWindowLevel'

interface WindowLevelControlProps {
  activePreset: WindowLevelMode
  maxHu: number
  minHu: number
  ww: number
  wl: number
  onCustomRange: (minHu: number, maxHu: number) => void
  onPreset: (preset: WindowLevelPreset) => void
}

const PRESET_KEYS = Object.keys(WINDOW_LEVEL_PRESETS) as WindowLevelPreset[]

function WindowLevelControl({
  activePreset,
  maxHu,
  minHu,
  ww,
  wl,
  onCustomRange,
  onPreset,
}: WindowLevelControlProps) {
  const [customMin, setCustomMin] = useState(String(minHu))
  const [customMax, setCustomMax] = useState(String(maxHu))

  useEffect(() => {
    setCustomMin(String(minHu))
    setCustomMax(String(maxHu))
  }, [maxHu, minHu])

  function updateCustomRange(nextMin: string, nextMax: string) {
    setCustomMin(nextMin)
    setCustomMax(nextMax)
    if (nextMin.trim() === '' || nextMax.trim() === '') {
      return
    }
    const parsedMin = Number(nextMin)
    const parsedMax = Number(nextMax)
    if (Number.isFinite(parsedMin) && Number.isFinite(parsedMax) && parsedMax > parsedMin) {
      onCustomRange(parsedMin, parsedMax)
    }
  }

  const customRangeInvalid =
    customMin.trim() === '' ||
    customMax.trim() === '' ||
    !Number.isFinite(Number(customMin)) ||
    !Number.isFinite(Number(customMax)) ||
    Number(customMax) <= Number(customMin)

  return (
    <Stack spacing={1.1} data-window-width={ww} data-window-level={wl}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: '0.22em' }}>
          Window / Level
        </Typography>
        <Chip label={`WW ${ww}`} variant="outlined" size="small" />
        <Chip label={`WL ${wl}`} variant="outlined" size="small" />
      </Stack>

      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {PRESET_KEYS.map((preset) => (
          <Button
            key={preset}
            variant={activePreset === preset ? 'contained' : 'outlined'}
            size="small"
            onClick={() => onPreset(preset)}
            sx={presetButtonSx(activePreset === preset)}
            title={`${WINDOW_LEVEL_PRESETS[preset].min} to ${WINDOW_LEVEL_PRESETS[preset].max} HU`}
          >
            {WINDOW_LEVEL_PRESETS[preset].label}
          </Button>
        ))}
        <Button
          variant={activePreset === 'custom' ? 'contained' : 'outlined'}
          size="small"
          onClick={() => onCustomRange(minHu, maxHu)}
          sx={presetButtonSx(activePreset === 'custom')}
        >
          Custom
        </Button>
      </Stack>

      {activePreset === 'custom' ? (
        <Stack direction="row" spacing={1} alignItems="center">
          <TextField
            error={customRangeInvalid}
            label="Min HU"
            onChange={(event) => updateCustomRange(event.target.value, customMax)}
            size="small"
            type="number"
            value={customMin}
            sx={{ flex: 1 }}
          />
          <TextField
            error={customRangeInvalid}
            label="Max HU"
            onChange={(event) => updateCustomRange(customMin, event.target.value)}
            size="small"
            type="number"
            value={customMax}
            sx={{ flex: 1 }}
          />
        </Stack>
      ) : null}
    </Stack>
  )
}

function presetButtonSx(active: boolean) {
  return {
    borderRadius: 5,
    minWidth: 0,
    px: 1.25,
    py: 0.35,
    fontWeight: 700,
    ...(active
      ? {
          bgcolor: '#67d7ff',
          borderColor: '#67d7ff',
          color: '#05131d',
          '&:hover': {
            bgcolor: '#67d7ff',
            borderColor: '#67d7ff',
          },
        }
      : {}),
  }
}

export default WindowLevelControl
