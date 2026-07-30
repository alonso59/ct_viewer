import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Button,
  Chip,
  Stack,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'

import type { CaseDossier } from '../../services/api'

interface MetadataTabProps {
  dossier: CaseDossier | null
  dossierPath: string
}

function MetadataTab({ dossier, dossierPath }: MetadataTabProps) {
  return (
    <Stack spacing={1} data-testid="metadata-tab-panel">
      <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
        <Stack spacing={0.25}>
          <Typography variant="subtitle2">Compact metadata summary</Typography>
          <Typography variant="caption" color="text.secondary">
            Full categorized case data belongs in the dossier.
          </Typography>
        </Stack>
        <Button component={RouterLink} to={dossierPath} size="small" variant="outlined">
          Open full dossier
        </Button>
      </Stack>

      {dossier ? (
        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
          <Chip label={`Core ${Object.keys(dossier.core).length}`} size="small" />
          <Chip label={`Acquisition ${Object.keys(dossier.acquisition).length}`} size="small" />
          <Chip
            label={`SEG/VOI ${Object.keys(dossier.segmentation_voi).length}`}
            size="small"
          />
          <Chip
            label={`QC ${Object.keys(dossier.preprocessing_qc).length}`}
            size="small"
          />
          <Chip
            label={`Raw rows ${dossier.advanced_raw_fields.length}`}
            size="small"
            variant="outlined"
          />
        </Stack>
      ) : (
        <Typography variant="body2" color="text.secondary">
          Metadata is unavailable.
        </Typography>
      )}

      <Accordion data-testid="advanced-metadata">
        <AccordionSummary expandIcon={<span>+</span>}>
          <Typography>Grouped metadata preview</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={1}>
            {dossier ? (
              <>
                <MetadataPreview title="Case core" value={dossier.core} />
                <MetadataPreview title="Acquisition" value={dossier.acquisition} />
                <MetadataPreview title="Segmentation / VOI" value={dossier.segmentation_voi} />
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">
                No grouped metadata available.
              </Typography>
            )}
          </Stack>
        </AccordionDetails>
      </Accordion>
    </Stack>
  )
}

function MetadataPreview({ title, value }: { title: string; value: Record<string, unknown> }) {
  const entries = Object.entries(value).slice(0, 6)
  return (
    <Stack spacing={0.35}>
      <Typography variant="caption" color="text.secondary">
        {title}
      </Typography>
      {entries.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No fields.
        </Typography>
      ) : (
        entries.map(([key, fieldValue]) => (
          <Typography key={key} variant="body2">
            <Typography component="span" variant="body2" color="text.secondary">
              {key}:{' '}
            </Typography>
            {String(fieldValue ?? '-')}
          </Typography>
        ))
      )}
    </Stack>
  )
}

export default MetadataTab
