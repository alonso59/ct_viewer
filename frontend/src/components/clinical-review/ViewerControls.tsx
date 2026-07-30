import { Divider, Stack, Typography } from '@mui/material'
import type { Dispatch, SetStateAction } from 'react'

import LayerToggle from '../viewer/LayerToggle'
import OpacitySlider from '../viewer/OpacitySlider'
import WindowLevelControl from '../viewer/WindowLevelControl'
import type { useWindowLevel } from '../viewer/useWindowLevel'
import { LAYER_META } from './reviewUi'

interface ViewerControlsProps {
  availableLabels: number[]
  layerState: Record<1 | 2 | 3, { visible: boolean; opacity: number }>
  setLayerState: Dispatch<SetStateAction<Record<1 | 2 | 3, { visible: boolean; opacity: number }>>>
  windowLevel: ReturnType<typeof useWindowLevel>
}

function ViewerControls({
  availableLabels,
  layerState,
  setLayerState,
  windowLevel,
}: ViewerControlsProps) {
  return (
    <Stack spacing={1.25}>
      <WindowLevelControl ww={windowLevel.ww} wl={windowLevel.wl} onPreset={windowLevel.applyPreset} />
      <Divider />
      <Typography variant="caption" color="text.secondary">
        Mask Layers
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
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
    </Stack>
  )
}

export default ViewerControls
