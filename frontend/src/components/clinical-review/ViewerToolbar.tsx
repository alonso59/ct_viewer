import {
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  type SelectChangeEvent,
} from '@mui/material'
import type { ReactNode } from 'react'

import type { Axis, CanonicalPhase, Scope } from '../../services/api'

interface ViewerToolbarProps {
  focusedPlane: Axis
  onFocusedPlaneChange: (axis: Axis) => void
  onOverlayEnabledChange: () => void
  onPhaseChange: (phase: CanonicalPhase) => void
  onScanIdxChange: (scanIdx: string) => void
  onScopeChange: (scope: Scope) => void
  onSideChange: (side: string) => void
  overlayEnabled: boolean
  phases: CanonicalPhase[]
  scanOptions: string[]
  scope: Scope
  selectedPhase: CanonicalPhase | null
  selectedScanIdx: string
  selectedSide: string
  sideOptions: string[]
  sideSelectionActive: boolean
}

function ViewerToolbar({
  focusedPlane,
  onFocusedPlaneChange,
  onOverlayEnabledChange,
  onPhaseChange,
  onScanIdxChange,
  onScopeChange,
  onSideChange,
  overlayEnabled,
  phases,
  scanOptions,
  scope,
  selectedPhase,
  selectedScanIdx,
  selectedSide,
  sideOptions,
  sideSelectionActive,
}: ViewerToolbarProps) {
  return (
    <Paper elevation={0} data-testid="viewer-toolbar" sx={{ px: 1.1, py: 1 }}>
      <Stack direction="row" spacing={1.1} flexWrap="wrap" useFlexGap alignItems="center">
        <ToolbarGroup label="Phase">
          {phases.map((phase) => (
            <Chip
              key={phase}
              label={phase}
              color={phase === selectedPhase ? 'primary' : 'default'}
              variant={phase === selectedPhase ? 'filled' : 'outlined'}
              onClick={() => onPhaseChange(phase)}
              data-testid="phase-chip"
            />
          ))}
        </ToolbarGroup>

        <ToolbarGroup label="Scope">
          <ToggleButtonGroup
            exclusive
            size="small"
            value={scope}
            onChange={(_, value: Scope | null) => {
              if (value) {
                onScopeChange(value)
              }
            }}
          >
            <ToggleButton value="complete">Complete</ToggleButton>
            <ToggleButton value="voi">VOI</ToggleButton>
          </ToggleButtonGroup>
        </ToolbarGroup>

        <ToolbarGroup label="Plane">
          <ToggleButtonGroup
            exclusive
            size="small"
            value={focusedPlane}
            onChange={(_, value: Axis | null) => {
              if (value) {
                onFocusedPlaneChange(value)
              }
            }}
          >
            <ToggleButton value="axial">Axial</ToggleButton>
            <ToggleButton value="coronal">Coronal</ToggleButton>
            <ToggleButton value="sagittal">Sagittal</ToggleButton>
          </ToggleButtonGroup>
        </ToolbarGroup>

        <ToolbarGroup label="Overlay">
          <ToggleButton
            size="small"
            selected={overlayEnabled}
            value="overlay"
            onChange={onOverlayEnabledChange}
          >
            {overlayEnabled ? 'On' : 'Off'}
          </ToggleButton>
        </ToolbarGroup>

        {scanOptions.length > 1 ? (
          <ToolbarGroup label="Scan">
            <FormControl size="small" sx={{ minWidth: 112 }} data-testid="scan-idx-selector">
              <InputLabel id="scan-idx-label">scan_idx</InputLabel>
              <Select
                labelId="scan-idx-label"
                label="scan_idx"
                value={selectedScanIdx}
                onChange={(event: SelectChangeEvent) => onScanIdxChange(event.target.value)}
              >
                {scanOptions.map((scanIdx) => (
                  <MenuItem key={scanIdx || 'blank'} value={scanIdx}>
                    {scanIdx || '-'}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </ToolbarGroup>
        ) : null}

        {sideSelectionActive ? (
          <ToolbarGroup label="Side">
            <FormControl size="small" sx={{ minWidth: 96 }} data-testid="side-selector">
              <InputLabel id="side-label">Side</InputLabel>
              <Select
                labelId="side-label"
                label="Side"
                value={selectedSide}
                onChange={(event: SelectChangeEvent) => onSideChange(event.target.value)}
              >
                {sideOptions.map((side) => (
                  <MenuItem key={side} value={side}>
                    {side}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </ToolbarGroup>
        ) : null}
      </Stack>
    </Paper>
  )
}

function ToolbarGroup({ children, label }: { children: ReactNode; label: string }) {
  return (
    <Stack spacing={0.38} sx={{ minWidth: 0 }}>
      <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: '0.14em' }}>
        {label}
      </Typography>
      <Stack direction="row" spacing={0.65} alignItems="center" flexWrap="wrap" useFlexGap>
        {children}
      </Stack>
    </Stack>
  )
}

export default ViewerToolbar
