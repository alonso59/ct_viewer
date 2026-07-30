import { useEffect, type ReactNode } from 'react'
import {
  Box,
  Button,
  SvgIcon,
  Tooltip,
  Typography,
} from '@mui/material'

import { viewerControlButtonSx } from './viewerControlStyles'

interface ExpandablePanelProps {
  axisLabel: string
  caption: string
  accent: string
  expanded: boolean
  onToggleExpand: () => void
  children: ReactNode
}

function ExpandablePanel({
  axisLabel,
  accent,
  expanded,
  onToggleExpand,
  children,
}: ExpandablePanelProps) {
  useEffect(() => {
    if (!expanded) {
      return
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onToggleExpand()
      }
    }

    window.addEventListener('keydown', handleEscape)
    return () => {
      window.removeEventListener('keydown', handleEscape)
    }
  }, [expanded, onToggleExpand])

  const controlLabel = expanded ? 'Restore' : 'Expand'
  const tooltipLabel = expanded ? 'Restore view' : 'Expand view'

  return (
    <Box
      data-expanded={expanded ? 'true' : 'false'}
      data-panel={axisLabel}
      sx={{
        height: '100%',
        minHeight: 0,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        outline: expanded ? `1px solid ${accent}` : 'none',
        outlineOffset: '-1px',
        backgroundColor: '#000',
      }}
    >
      <Box
        display="flex"
        flexDirection="row"
        alignItems="center"
        justifyContent="space-between"
        onDoubleClick={onToggleExpand}
        sx={{
          px: 0.75,
          py: 0.25,
          borderBottom: '1px solid rgba(255,255,255,0.07)',
          backgroundColor: 'rgba(0,0,0,0.72)',
          cursor: 'pointer',
          userSelect: 'none',
          minHeight: 36,
          flexShrink: 0,
        }}
      >
        <Box
          sx={{
            px: 0.65,
            py: 0.1,
            borderRadius: 999,
            border: '1px solid',
            borderColor: accent,
            color: accent,
            lineHeight: 1,
            flexShrink: 0,
          }}
        >
          <Typography sx={{ fontSize: '0.62rem', fontWeight: 800, lineHeight: 1 }}>
            {axisLabel}
          </Typography>
        </Box>

        <Tooltip title={tooltipLabel}>
          <Button
            aria-label={tooltipLabel}
            onClick={(event) => {
              event.stopPropagation()
              onToggleExpand()
            }}
            startIcon={expanded ? <RestoreViewIcon /> : <ExpandViewIcon />}
            sx={{
              ...viewerControlButtonSx(expanded),
              minHeight: 32,
              minWidth: expanded ? 82 : 78,
              px: 0.8,
              py: 0.2,
            }}
          >
            {controlLabel}
          </Button>
        </Tooltip>
      </Box>

      <Box sx={{ flex: 1, minHeight: 0, minWidth: 0 }}>{children}</Box>
    </Box>
  )
}

function ExpandViewIcon() {
  return (
    <SvgIcon>
      <path d="M5 5h6v2H8.41l3.3 3.29-1.42 1.42L7 8.41V11H5V5Zm8 0h6v6h-2V8.41l-3.29 3.3-1.42-1.42 3.3-3.29H13V5ZM7 15.59 10.29 12.3l1.42 1.41L8.41 17H11v2H5v-6h2v2.59Zm9.59 1.41-3.3-3.29 1.42-1.41L18 15.59V13h2v6h-6v-2h2.59Z" />
    </SvgIcon>
  )
}

function RestoreViewIcon() {
  return (
    <SvgIcon>
      <path d="M9 3h2v6H5V7h2.59L4.29 3.71 5.71 2.3 9 5.59V3Zm6 0 3.29-3.3 1.42 1.41L16.41 7H19v2h-6V3h2v2.59ZM5 15h6v6H9v-2.59l-3.29 3.3-1.42-1.42L7.59 17H5v-2Zm8 0h6v2h-2.59l3.3 3.29-1.42 1.42L15 18.41V21h-2v-6Z" />
    </SvgIcon>
  )
}

export default ExpandablePanel
