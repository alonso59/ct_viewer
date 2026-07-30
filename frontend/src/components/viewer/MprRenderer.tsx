import { Box, Stack } from '@mui/material'

import type { Axis, SliceQuery } from '../../services/api'
import {
  DEFAULT_MPR_RENDERER_MODE,
  type MprRendererMode,
} from '../../services/mprRendererConfig'
import SliceSlider from './SliceSlider'
import SliceView from './SliceView'
import type { useSliceNavigation } from './useSliceNavigation'
import ViewerGrid2x2, { type ViewerPanelOverride } from './ViewerGrid2x2'

const MPR_PANEL_ACCENTS: Record<Axis, string> = {
  axial: '#fb923c',
  coronal: '#ef4444',
  sagittal: '#22c55e',
}

const MPR_AXES: Axis[] = ['axial', 'sagittal', 'coronal']

type MprNavigation = ReturnType<typeof useSliceNavigation>

interface MprRendererProps {
  errorText?: string | null
  navigation: MprNavigation
  onHandleExpired?: () => void
  onWindowLevelDrag: (
    startWw: number,
    startWl: number,
    deltaX: number,
    deltaY: number,
  ) => void
  query: SliceQuery
  rendererMode?: MprRendererMode
  requestKey: string | null
  surfacePanel: ViewerPanelOverride
  wl: number
  ww: number
}

function MprRenderer({
  errorText,
  navigation,
  onHandleExpired,
  onWindowLevelDrag,
  query,
  rendererMode = DEFAULT_MPR_RENDERER_MODE,
  requestKey,
  surfacePanel,
  wl,
  ww,
}: MprRendererProps) {
  const panels = MPR_AXES.reduce<Partial<Record<Axis, ViewerPanelOverride>>>((current, axis) => {
    current[axis] = buildMprPanel({
      axis,
      errorText,
      navigation,
      onHandleExpired,
      onWindowLevelDrag,
      query,
      requestKey,
      wl,
      ww,
    })
    return current
  }, {})

  return (
    <Box
      data-mpr-active-renderer="png"
      data-mpr-has-load-handle={String(Boolean(requestKey))}
      data-mpr-requested-renderer={rendererMode}
      sx={{ minWidth: 0 }}
    >
      <ViewerGrid2x2 panels={{ ...panels, surface: surfacePanel }} />
    </Box>
  )
}

function buildMprPanel({
  axis,
  errorText,
  navigation,
  onHandleExpired,
  onWindowLevelDrag,
  query,
  requestKey,
  wl,
  ww,
}: {
  axis: Axis
  errorText?: string | null
  navigation: MprNavigation
  onHandleExpired?: () => void
  onWindowLevelDrag: (
    startWw: number,
    startWl: number,
    deltaX: number,
    deltaY: number,
  ) => void
  query: SliceQuery
  requestKey: string | null
  wl: number
  ww: number
}): ViewerPanelOverride {
  const index = navigation.sliceIndices[axis]
  const maxIndex = navigation.getMaxIndex(axis)

  return {
    caption: describeSlice(axis, index, maxIndex),
    content: (
      <PngMprPanel
        accent={MPR_PANEL_ACCENTS[axis]}
        axis={axis}
        crosshair={navigation.getCrosshair(axis)}
        errorText={errorText}
        index={index}
        maxIndex={maxIndex}
        onCrosshairChange={(point) => navigation.setFromPanelPosition(axis, point)}
        onHandleExpired={onHandleExpired}
        onSliceChange={(nextIndex) => navigation.setSlice(axis, nextIndex)}
        onWindowLevelDrag={onWindowLevelDrag}
        query={query}
        requestKey={requestKey}
        wl={wl}
        ww={ww}
      />
    ),
  }
}

function PngMprPanel({
  accent,
  axis,
  crosshair,
  errorText,
  index,
  maxIndex,
  onCrosshairChange,
  onHandleExpired,
  onSliceChange,
  onWindowLevelDrag,
  query,
  requestKey,
  wl,
  ww,
}: {
  accent: string
  axis: Axis
  crosshair: { x: number; y: number }
  errorText?: string | null
  index: number
  maxIndex: number
  onCrosshairChange: (point: { x: number; y: number }) => void
  onHandleExpired?: () => void
  onSliceChange: (index: number) => void
  onWindowLevelDrag: (
    startWw: number,
    startWl: number,
    deltaX: number,
    deltaY: number,
  ) => void
  query: SliceQuery
  requestKey: string | null
  wl: number
  ww: number
}) {
  return (
    <Stack
      spacing={0.75}
      sx={{
        height: '100%',
        p: 0.5,
        background: 'transparent',
      }}
    >
      <SliceView
        accent={accent}
        axis={axis}
        crosshair={crosshair}
        disabled={!requestKey}
        errorText={errorText}
        index={index}
        maxIndex={maxIndex}
        onCrosshairChange={onCrosshairChange}
        onHandleExpired={onHandleExpired}
        onSliceChange={onSliceChange}
        onWindowLevelDrag={onWindowLevelDrag}
        query={query}
        requestKey={requestKey}
        wl={wl}
        ww={ww}
      />
      <SliceSlider
        axis={axis}
        color={accent}
        index={index}
        maxIndex={maxIndex}
        onChange={onSliceChange}
      />
    </Stack>
  )
}

function describeSlice(axis: Axis, index: number, maxIndex: number): string {
  return `${axis.toUpperCase()} ${index + 1} / ${maxIndex + 1}`
}

export default MprRenderer
