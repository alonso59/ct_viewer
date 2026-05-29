import { Box, Button, Stack, Typography } from '@mui/material'
import { useEffect, useState, type ReactNode } from 'react'

import ExpandablePanel from './ExpandablePanel'
import { viewerControlButtonSx } from './viewerControlStyles'

const PANEL_DEFS = [
  {
    id: 'axial',
    label: 'AXI',
    accent: '#fbbf24',
    caption: 'Axial viewport placeholder',
    placeholder: 'Slice view and navigation land here in M8.',
  },
  {
    id: 'coronal',
    label: 'COR',
    accent: '#ef4444',
    caption: 'Coronal viewport placeholder',
    placeholder: 'Coronal image panel will reuse the shared slice API.',
  },
  {
    id: 'sagittal',
    label: 'SAG',
    accent: '#22c55e',
    caption: 'Sagittal viewport placeholder',
    placeholder: 'Crosshair sync and scrolling arrive next.',
  },
  {
    id: 'surface',
    label: '3D',
    accent: '#f5f5f5',
    caption: 'Surface viewport placeholder',
    placeholder: 'Mesh rendering and blend controls arrive in M9.',
  },
] as const

type PanelId = (typeof PANEL_DEFS)[number]['id']

interface PanelOverride {
  caption?: string
  content?: ReactNode
}

interface ViewerGrid2x2Props {
  legend?: ReactNode
  layout?: 'standard' | 'cockpit'
  panels?: Partial<Record<PanelId, PanelOverride>>
}

function ViewerGrid2x2({ legend, layout = 'standard', panels = {} }: ViewerGrid2x2Props) {
  const [expandedPanel, setExpandedPanel] = useState<PanelId | null>(null)
  const hasExpandedPanel = expandedPanel !== null
  const cockpit = layout === 'cockpit'

  useEffect(() => {
    if (!hasExpandedPanel) {
      // If a panel expansion briefly introduced horizontal overflow, reset to the left edge.
      window.scrollTo({ left: 0, top: window.scrollY, behavior: 'auto' })
    }
  }, [hasExpandedPanel])

  return (
    <Box
      data-testid="viewer-grid-2x2"
      sx={{
        position: 'relative',
        display: 'grid',
        height: cockpit ? '100%' : 'auto',
        width: '100%',
        maxWidth: '100%',
        mx: 0,
        gridTemplateColumns: hasExpandedPanel
          ? 'minmax(0, 1fr)'
          : { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 1fr) minmax(0, 1fr)' },
        gridTemplateRows: hasExpandedPanel
          ? cockpit
            ? 'minmax(0, 1fr)'
            : 'minmax(320px, min(82vh, 980px))'
          : cockpit
            ? {
                xs: 'repeat(4, minmax(260px, auto))',
                sm: 'repeat(4, minmax(300px, auto))',
                lg: 'repeat(2, minmax(0, 1fr))',
              }
            : {
                xs: 'repeat(4, minmax(260px, auto))',
                sm: 'repeat(4, minmax(300px, auto))',
                lg: 'repeat(2, auto)',
              },
        gap: '1px',
        p: 0,
        borderRadius: 0,
        backgroundColor: '#111',
        minHeight: hasExpandedPanel ? 320 : { xs: 'auto', lg: cockpit ? 0 : 0 },
        minWidth: 0,
      }}
    >
      {legend}
      {hasExpandedPanel ? (
        <Button
          aria-label="Reset layout"
          onClick={() => setExpandedPanel(null)}
          sx={{
            ...viewerControlButtonSx(false),
            position: 'absolute',
            top: 6,
            right: 6,
            zIndex: 8,
            minWidth: 96,
          }}
        >
          Reset layout
        </Button>
      ) : null}
      {PANEL_DEFS.map((panel) => {
        const expanded = expandedPanel === panel.id
        const hidden = expandedPanel !== null && !expanded

        return (
          <Box
            key={panel.id}
            sx={{
              minWidth: 0,
              minHeight: 0,
              height: cockpit || hasExpandedPanel ? '100%' : 'auto',
              display: hidden ? 'none' : 'block',
              ...(expandedPanel
                ? {
                    gridColumn: '1 / -1',
                    gridRow: '1 / -1',
                  }
                : {}),
            }}
          >
            <ExpandablePanel
              axisLabel={panel.label}
              caption={panels[panel.id]?.caption ?? panel.caption}
              accent={panel.accent}
              expanded={expanded}
              onToggleExpand={() =>
                setExpandedPanel((current) => (current === panel.id ? null : panel.id))
              }
            >
              {panels[panel.id]?.content ?? (
                <Stack
                  spacing={2}
                  justifyContent="space-between"
                  sx={{
                    height: '100%',
                    p: 2.5,
                    background:
                      'linear-gradient(180deg, rgba(255,255,255,0.015), rgba(255,255,255,0.03))',
                  }}
                >
                  <Box
                    sx={{
                      flex: 1,
                      minHeight: 0,
                      borderRadius: 3,
                      border: '1px dashed',
                      borderColor: 'divider',
                      background:
                        'radial-gradient(circle at top, rgba(125, 211, 252, 0.08), transparent 42%), rgba(255,255,255,0.015)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      textAlign: 'center',
                      px: 3,
                    }}
                  >
                    <Stack spacing={1.25} alignItems="center">
                      <Typography variant="h5">{panel.label}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {panel.placeholder}
                      </Typography>
                    </Stack>
                  </Box>

                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography variant="caption" color="text.secondary">
                      Double-click header or use the corner control to expand.
                    </Typography>
                    <Typography
                      variant="caption"
                      sx={{
                        px: 1,
                        py: 0.4,
                        borderRadius: 999,
                        border: '1px solid',
                        borderColor: panel.accent,
                        color: panel.accent,
                      }}
                    >
                      Placeholder
                    </Typography>
                  </Stack>
                </Stack>
              )}
            </ExpandablePanel>
          </Box>
        )
      })}
    </Box>
  )
}

export default ViewerGrid2x2
