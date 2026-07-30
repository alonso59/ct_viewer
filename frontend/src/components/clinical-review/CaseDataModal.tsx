import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useMemo, useState } from 'react'

import type { CaseDossier, CaseInventoryRow, CaseSummary, CurationDecision } from '../../services/api'
import { formatDate, formatStatus, pathStatusLabel, statusChipColor } from './reviewUi'

interface CaseDataModalProps {
  caseSummary: CaseSummary | null
  decisions: CurationDecision[]
  dossier: CaseDossier | null
  open: boolean
  onClose: () => void
  rows: CaseInventoryRow[]
  selectedRow: CaseInventoryRow | null
}

function CaseDataModal({
  caseSummary,
  decisions,
  dossier,
  open,
  onClose,
  rows,
  selectedRow,
}: CaseDataModalProps) {
  const [query, setQuery] = useState('')
  const normalizedQuery = query.trim().toLowerCase()

  const sectionData = useMemo(
    () => ({
      summary: {
        case_id: caseSummary?.case_id ?? dossier?.case_id ?? '-',
        patient_id: caseSummary?.patient_id ?? '-',
        group: caseSummary?.group ?? '-',
        qc_status: formatStatus(caseSummary?.latest_curation_status),
        warnings: String(caseSummary?.warning_count ?? rows.reduce((sum, row) => sum + row.qc_warnings.length, 0)),
      },
      availability: {
        phases: caseSummary?.available_phases.join(', ') || Array.from(new Set(rows.map((row) => row.canonical_phase))).join(', '),
        scans: String(caseSummary?.scan_count ?? new Set(rows.map((row) => row.scan_idx)).size),
        complete_ct: rows.some((row) => row.scope_availability.complete) ? 'available' : 'missing',
        seg: rows.some((row) => row.seg_path.status === 'exists') ? 'available' : 'missing',
        voi_images: String(caseSummary?.voi_image_count ?? rows.filter((row) => row.voi_image_path.status === 'exists').length),
        voi_masks: String(caseSummary?.voi_mask_count ?? rows.filter((row) => row.voi_mask_path.status === 'exists').length),
      },
      segmentation: {
        selected_source: selectedRow ? `${selectedRow.canonical_phase} / scan ${selectedRow.scan_idx ?? '-'}` : '-',
        selected_side: selectedRow?.side ?? '-',
        selected_scope_available: selectedRow
          ? `complete ${String(selectedRow.scope_availability.complete)}, voi ${String(selectedRow.scope_availability.voi)}`
          : '-',
        seg_status: selectedRow ? pathStatusLabel(selectedRow.seg_path.status) : '-',
        voi_image_status: selectedRow ? pathStatusLabel(selectedRow.voi_image_path.status) : '-',
        voi_mask_status: selectedRow ? pathStatusLabel(selectedRow.voi_mask_path.status) : '-',
      },
    }),
    [caseSummary, dossier?.case_id, rows, selectedRow],
  )

  function matches(value: Record<string, string>): boolean {
    if (!normalizedQuery) {
      return true
    }
    return Object.entries(value).some(([key, entryValue]) =>
      `${key} ${entryValue}`.toLowerCase().includes(normalizedQuery),
    )
  }

  const rawFieldCount = dossier?.advanced_raw_fields.length ?? 0

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="lg" data-testid="case-data-modal">
      <DialogTitle>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography variant="h5">Case Data</Typography>
          <Chip label={caseSummary?.case_id ?? dossier?.case_id ?? 'Unknown case'} color="primary" size="small" />
          <Chip label={`${rows.reduce((sum, row) => sum + row.qc_warnings.length, 0)} warnings`} color="warning" size="small" variant="outlined" />
        </Stack>
      </DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          <TextField
            autoFocus
            label="Search metadata"
            size="small"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            inputProps={{ 'aria-label': 'Search metadata' }}
          />

          <Grid container spacing={1.5}>
            {matches(sectionData.summary) ? (
              <Grid size={{ xs: 12, md: 6 }}>
                <ReportSection title="Case Summary" values={sectionData.summary} />
              </Grid>
            ) : null}
            {matches(sectionData.availability) ? (
              <Grid size={{ xs: 12, md: 6 }}>
                <ReportSection title="Imaging Availability" values={sectionData.availability} />
              </Grid>
            ) : null}
            {matches(sectionData.segmentation) ? (
              <Grid size={{ xs: 12, md: 6 }}>
                <ReportSection title="Segmentation & VOI" values={sectionData.segmentation} />
              </Grid>
            ) : null}
            <Grid size={{ xs: 12, md: 6 }}>
              <Stack spacing={1.1} sx={sectionBoxSx}>
                <Typography variant="subtitle2">QC History</Typography>
                {decisions.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    No saved QC history.
                  </Typography>
                ) : (
                  decisions.slice(0, 6).map((decision) => (
                    <Stack key={decision.review_id} spacing={0.4}>
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                        <Chip label={formatStatus(decision.status)} color={statusChipColor(decision.status)} size="small" />
                        <Chip label={decision.reviewer || 'Unknown reviewer'} size="small" variant="outlined" />
                      </Stack>
                      <Typography variant="caption" color="text.secondary">
                        {formatDate(decision.reviewed_at)}
                      </Typography>
                      <Typography variant="body2">{decision.comment || 'No comment.'}</Typography>
                      <Divider />
                    </Stack>
                  ))
                )}
              </Stack>
            </Grid>
          </Grid>

          <Accordion data-testid="technical-paths" defaultExpanded={false}>
            <AccordionSummary expandIcon={<span>+</span>}>
              <Typography>Technical paths hidden by default</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={0.5}>
                {selectedRow ? (
                  <>
                    <Typography variant="body2">NIfTI: {selectedRow.nifti_path.resolved ?? '-'}</Typography>
                    <Typography variant="body2">SEG: {selectedRow.seg_path.resolved ?? '-'}</Typography>
                    <Typography variant="body2">VOI image: {selectedRow.voi_image_path.resolved ?? '-'}</Typography>
                    <Typography variant="body2">VOI mask: {selectedRow.voi_mask_path.resolved ?? '-'}</Typography>
                  </>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    Select a source to inspect technical paths.
                  </Typography>
                )}
              </Stack>
            </AccordionDetails>
          </Accordion>

          <Accordion data-testid="raw-fields" defaultExpanded={false}>
            <AccordionSummary expandIcon={<span>+</span>}>
              <Typography>Raw fields hidden by default ({rawFieldCount})</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1}>
                {(dossier?.advanced_raw_fields ?? []).slice(0, 4).map((row, index) => (
                  <Typography key={index} variant="body2" sx={{ wordBreak: 'break-word' }}>
                    {JSON.stringify(row)}
                  </Typography>
                ))}
                {rawFieldCount === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    No raw fields available.
                  </Typography>
                ) : null}
              </Stack>
            </AccordionDetails>
          </Accordion>
        </Stack>
      </DialogContent>
    </Dialog>
  )
}

const sectionBoxSx = {
  height: '100%',
  p: 1.4,
  border: '1px solid',
  borderColor: 'divider',
  borderRadius: 1,
  backgroundColor: 'rgba(255,255,255,0.02)',
}

function ReportSection({ title, values }: { title: string; values: Record<string, string> }) {
  return (
    <Stack spacing={1.1} sx={sectionBoxSx}>
      <Typography variant="subtitle2">{title}</Typography>
      <Stack spacing={0.55}>
        {Object.entries(values).map(([key, value]) => (
          <Stack key={key} direction="row" spacing={1} justifyContent="space-between">
            <Typography variant="caption" color="text.secondary">
              {key.replaceAll('_', ' ')}
            </Typography>
            <Typography variant="body2" sx={{ textAlign: 'right', maxWidth: '58%', wordBreak: 'break-word' }}>
              {value || '-'}
            </Typography>
          </Stack>
        ))}
      </Stack>
    </Stack>
  )
}

export default CaseDataModal
