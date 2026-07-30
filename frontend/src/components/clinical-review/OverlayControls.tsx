import {
  Divider,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import type { Dispatch, SetStateAction } from 'react'

import LayerToggle from '../viewer/LayerToggle'
import OpacitySlider from '../viewer/OpacitySlider'
import WindowLevelControl from '../viewer/WindowLevelControl'
import type { useWindowLevel } from '../viewer/useWindowLevel'
import { LAYER_META } from './reviewUi'

export type OverlayMode = 'filled' | 'contour'

interface OverlayControlsProps {
  availableLabels: number[]
  layerState: Record<1 | 2 | 3, { visible: boolean; opacity: number }>
  mode: OverlayMode
  overlayEnabled: boolean
  setLayerState: Dispatch<SetStateAction<Record<1 | 2 | 3, { visible: boolean; opacity: number }>>>
  setMode: (mode: OverlayMode) => void
  setOverlayEnabled: (enabled: boolean) => void
  windowLevel: ReturnType<typeof useWindowLevel>
}

function OverlayControls({
  availableLabels,
  layerState,
  mode,
  overlayEnabled,
  setLayerState,
  setMode,
  setOverlayEnabled,
  windowLevel,
}: OverlayControlsProps) {
  return (
    <Stack spacing={1.15} data-testid="overlay-controls">
      <Stack spacing={0.35}>
        <Typography variant="overline" color="text.secondary">
          Layers / Overlays
        </Typography>
        <ToggleButtonGroup
          exclusive
          fullWidth
          size="small"
          value={overlayEnabled ? 'on' : 'off'}
          onChange={(_, value: 'on' | 'off' | null) => {
            if (value) {
              setOverlayEnabled(value === 'on')
            }
          }}
        >
          <ToggleButton value="on">On</ToggleButton>
          <ToggleButton value="off">Off</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      <ToggleButtonGroup
        exclusive
        fullWidth
        size="small"
        value={mode}
        onChange={(_, value: OverlayMode | null) => {
          if (value) {
            setMode(value)
          }
        }}
      >
        <ToggleButton value="filled" data-testid="overlay-mode-filled">
          Filled
        </ToggleButton>
        <ToggleButton value="contour" data-testid="overlay-mode-contour">
          Contour
        </ToggleButton>
      </ToggleButtonGroup>

      <Stack direction="row" spacing={0.55} flexWrap="wrap" useFlexGap>
        {[1, 2, 3].map((label) => (
          <LayerToggle
            key={label}
            checked={layerState[label as 1 | 2 | 3].visible}
            color={LAYER_META[label].color}
            disabled={!availableLabels.includes(label)}
            label={LAYER_META[label].label}
            onChange={(checked) =>
              setLayerState((current) => ({
                ...current,
                [label]: {
                  ...current[label as 1 | 2 | 3],
                  visible: checked,
                },
              }))
            }
          />
        ))}
      </Stack>

      {[1, 2, 3].map((label) => (
        <OpacitySlider
          key={label}
          color={LAYER_META[label].color}
          disabled={!availableLabels.includes(label) || !layerState[label as 1 | 2 | 3].visible}
          label={LAYER_META[label].label}
          onChange={(value) =>
            setLayerState((current) => ({
              ...current,
              [label]: {
                ...current[label as 1 | 2 | 3],
                opacity: value,
              },
            }))
          }
          value={layerState[label as 1 | 2 | 3].opacity}
        />
      ))}

      <Divider />
      <WindowLevelControl ww={windowLevel.ww} wl={windowLevel.wl} onPreset={windowLevel.applyPreset} />
    </Stack>
  )
}

export default OverlayControls
