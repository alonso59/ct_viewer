import { useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import {
  Box,
  Button,
  Chip,
  Divider,
  Popover,
  Stack,
  SvgIcon,
  Tooltip,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'

import BlendSlider from '../viewer/BlendSlider'
import LayerToggle from '../viewer/LayerToggle'
import OpacitySlider from '../viewer/OpacitySlider'
import WindowLevelControl from '../viewer/WindowLevelControl'
import type { useWindowLevel } from '../viewer/useWindowLevel'
import { viewerControlButtonSx, viewerHudSx } from '../viewer/viewerControlStyles'
import type { OverlayMode } from './OverlayControls'
import { LAYER_META } from './reviewUi'

export interface OverlayControlsPopoverProps {
  availableLabels: number[]
  blend: number
  blendDisabled: boolean
  layerState: Record<1 | 2 | 3, { visible: boolean; opacity: number }>
  mode: OverlayMode
  overlayEnabled: boolean
  setBlend: (value: number) => void
  setLayerState: Dispatch<SetStateAction<Record<1 | 2 | 3, { visible: boolean; opacity: number }>>>
  setMode: (mode: OverlayMode) => void
  setOverlayEnabled: (enabled: boolean) => void
  visibleLabels: number[]
  windowLevel: ReturnType<typeof useWindowLevel>
}

function TuneIcon() {
  return (
    <SvgIcon sx={{ fontSize: '1rem' }}>
      <path d="M3 17v2h6v-2H3zM3 5v2h10V5H3zm10 16v-2h8v-2h-8v-2h-2v6h2zM7 9v2H3v2h4v2h2V9H7zm14 4v-2H11v2h10zm-6-4h2V7h4V5h-4V3h-2v6z" />
    </SvgIcon>
  )
}

function formatOverlayMode(mode: OverlayMode): string {
  return mode === 'filled' ? 'Filled' : 'Contour'
}

function OverlayControlsPopover({
  availableLabels,
  blend,
  blendDisabled,
  layerState,
  mode,
  overlayEnabled,
  setBlend,
  setLayerState,
  setMode,
  setOverlayEnabled,
  visibleLabels,
  windowLevel,
}: OverlayControlsPopoverProps) {
  const [anchorEl, setAnchorEl] = useState<HTMLButtonElement | null>(null)
  const open = Boolean(anchorEl)

  return (
    <Box
      data-testid="overlay-legend"
      data-overlay-placement="top-center"
      sx={{
        position: 'absolute',
        left: '50%',
        top: 6,
        transform: 'translateX(-50%)',
        zIndex: 7,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 0.6,
        maxWidth: 'calc(100% - 96px)',
        pointerEvents: 'none',
      }}
    >
      <Box
        data-testid="overlay-status-hud"
        sx={{
          ...viewerHudSx,
          maxWidth: { xs: 260, sm: 380 },
        }}
      >
        <Stack direction="row" spacing={0.65} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography
            variant="caption"
            sx={{
              color: 'rgba(226,232,240,0.82)',
              fontSize: '0.66rem',
              fontWeight: 700,
              lineHeight: 1,
            }}
          >
            Overlay {formatOverlayMode(mode)}
          </Typography>
          {[1, 2, 3].map((label) => (
            <Chip
              key={label}
              label={LAYER_META[label].label}
              size="small"
              variant={visibleLabels.includes(label) ? 'filled' : 'outlined'}
              sx={{
                height: 19,
                opacity: visibleLabels.includes(label) ? 0.95 : 0.42,
                borderColor: LAYER_META[label].color,
                color: visibleLabels.includes(label) ? '#050505' : LAYER_META[label].color,
                backgroundColor: visibleLabels.includes(label)
                  ? LAYER_META[label].color
                  : 'transparent',
                fontSize: '0.62rem',
                '& .MuiChip-label': { px: 0.65 },
              }}
            />
          ))}
        </Stack>
      </Box>

      <Tooltip title="Overlay settings">
        <Button
          data-testid="overlay-controls-button"
          aria-label="Overlay settings"
          aria-pressed={open}
          onClick={(event) => setAnchorEl(event.currentTarget)}
          startIcon={<TuneIcon />}
          sx={{
            ...viewerControlButtonSx(open),
            minWidth: 92,
            pointerEvents: 'auto',
          }}
        >
          Overlay
        </Button>
      </Tooltip>

      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        marginThreshold={12}
        slotProps={{
          paper: {
            sx: {
              mt: 0.75,
              maxHeight: 'min(72vh, 560px)',
              overflow: 'auto',
              backgroundColor: 'rgba(18,18,18,0.96)',
              backdropFilter: 'blur(12px)',
              border: '1px solid',
              borderColor: 'rgba(255,255,255,0.18)',
              borderRadius: 1,
              boxShadow: '0 18px 44px rgba(0,0,0,0.45)',
            },
          },
        }}
      >
        <Box sx={{ p: 1.5, width: 248 }}>
          <Stack spacing={1.1}>
            {/* On / Off */}
            <Stack spacing={0.3}>
              <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.6rem' }}>
                Overlay
              </Typography>
              <ToggleButtonGroup
                exclusive
                fullWidth
                size="small"
                value={overlayEnabled ? 'on' : 'off'}
                onChange={(_, value: 'on' | 'off' | null) => {
                  if (value) setOverlayEnabled(value === 'on')
                }}
              >
                <ToggleButton value="on">On</ToggleButton>
                <ToggleButton value="off">Off</ToggleButton>
              </ToggleButtonGroup>
            </Stack>

            {/* Filled / Contour */}
            <ToggleButtonGroup
              exclusive
              fullWidth
              size="small"
              value={mode}
              onChange={(_, value: OverlayMode | null) => {
                if (value) setMode(value)
              }}
            >
              <ToggleButton value="filled" data-testid="overlay-mode-filled">
                Filled
              </ToggleButton>
              <ToggleButton value="contour" data-testid="overlay-mode-contour">
                Contour
              </ToggleButton>
            </ToggleButtonGroup>

            {/* Label toggles */}
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
                      [label]: { ...current[label as 1 | 2 | 3], visible: checked },
                    }))
                  }
                />
              ))}
            </Stack>

            {/* Per-label opacity */}
            {[1, 2, 3].map((label) => (
              <OpacitySlider
                key={label}
                color={LAYER_META[label].color}
                disabled={
                  !availableLabels.includes(label) || !layerState[label as 1 | 2 | 3].visible
                }
                label={LAYER_META[label].label}
                onChange={(value) =>
                  setLayerState((current) => ({
                    ...current,
                    [label]: { ...current[label as 1 | 2 | 3], opacity: value },
                  }))
                }
                value={layerState[label as 1 | 2 | 3].opacity}
              />
            ))}

            <Divider />
            <WindowLevelControl
              ww={windowLevel.ww}
              wl={windowLevel.wl}
              onPreset={windowLevel.applyPreset}
            />

            <Divider />
            <Stack spacing={0.3}>
              <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.6rem' }}>
                3D Surface
              </Typography>
              <BlendSlider disabled={blendDisabled} onChange={setBlend} value={blend} />
            </Stack>
          </Stack>
        </Box>
      </Popover>
    </Box>
  )
}

export default OverlayControlsPopover
