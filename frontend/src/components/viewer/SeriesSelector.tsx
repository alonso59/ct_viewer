import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from '@mui/material'

import {
  apiClient,
  type SeriesInfo,
  getApiErrorMessage,
} from '../../services/api'

interface SeriesSelectorProps {
  datasetId: string
  patientId: string
  onSeriesChange?: (series: SeriesInfo | null) => void
  onSeriesListLoaded?: (seriesList: SeriesInfo[]) => void
  preferredSeriesId?: string | null
  reloadKey?: number
}

function seriesOptionKey(series: SeriesInfo): string {
  return `${series.series_id}::${series.storage_path ?? ''}`
}

function SeriesSelector({
  datasetId,
  patientId,
  onSeriesChange,
  onSeriesListLoaded,
  preferredSeriesId = null,
  reloadKey = 0,
}: SeriesSelectorProps) {
  const [requestState, setRequestState] = useState<{
    scope: string | null
    seriesList: SeriesInfo[]
    error: string | null
  }>({
    scope: null,
    seriesList: [],
    error: null,
  })
  const [selectedSeriesKey, setSelectedSeriesKey] = useState('')
  const scope = `${datasetId}:${patientId}:${reloadKey}`
  const loading = requestState.scope !== scope
  const seriesList = requestState.scope === scope ? requestState.seriesList : []
  const error = requestState.scope === scope ? requestState.error : null

  useEffect(() => {
    let active = true

    apiClient
      .listSeries(datasetId, patientId)
      .then((series) => {
        if (!active) {
          return
        }

        setRequestState({
          scope,
          seriesList: series,
          error: null,
        })
        onSeriesListLoaded?.(series)

        const preferredSeries =
          preferredSeriesId !== null
            ? (series.find((entry) => entry.series_id === preferredSeriesId) ?? null)
            : null
        const defaultSeries = preferredSeries ?? series[0] ?? null
        setSelectedSeriesKey(defaultSeries ? seriesOptionKey(defaultSeries) : '')
        onSeriesChange?.(defaultSeries)
      })
      .catch((requestError) => {
        if (!active) {
          return
        }

        setRequestState({
          scope,
          seriesList: [],
          error: getApiErrorMessage(requestError),
        })
        onSeriesListLoaded?.([])
        setSelectedSeriesKey('')
        onSeriesChange?.(null)
      })

    return () => {
      active = false
    }
  }, [datasetId, onSeriesChange, onSeriesListLoaded, patientId, preferredSeriesId, reloadKey, scope])

  const selectedSeries =
    seriesList.find((series) => seriesOptionKey(series) === selectedSeriesKey) ?? null

  return (
    <Stack spacing={1.25} sx={{ minWidth: 0, width: '100%' }}>
      <FormControl fullWidth disabled={loading || seriesList.length === 0}>
        <InputLabel id="series-selector-label">Series</InputLabel>
        <Select
          labelId="series-selector-label"
          label="Series"
          value={selectedSeriesKey}
          renderValue={(value) => {
            const series = seriesList.find((entry) => seriesOptionKey(entry) === value)
            if (!series) {
              return ''
            }
            return series.deleted ? `${series.filename} [DELETED]` : series.filename
          }}
          onChange={(event) => {
            const nextKey = event.target.value
            setSelectedSeriesKey(nextKey)
            onSeriesChange?.(
              seriesList.find((series) => seriesOptionKey(series) === nextKey) ?? null,
            )
          }}
        >
          {seriesList.map((series) => (
            <MenuItem key={seriesOptionKey(series)} value={seriesOptionKey(series)}>
              <Stack
                direction={{ xs: 'column', sm: 'row' }}
                spacing={{ xs: 0.5, sm: 1.25 }}
                alignItems={{ sm: 'center' }}
                sx={{ minWidth: 0 }}
              >
                <Typography
                  fontWeight={600}
                  sx={{
                    minWidth: 0,
                    overflowWrap: 'anywhere',
                    color: series.deleted ? 'error.main' : 'text.primary',
                    textDecoration: series.deleted ? 'line-through' : 'none',
                  }}
                >
                  {series.filename}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {series.type.toUpperCase()}
                </Typography>
                {series.deleted ? (
                  <Chip label="DELETED" size="small" color="error" variant="filled" />
                ) : null}
              </Stack>
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {loading ? (
        <Stack direction="row" spacing={1} alignItems="center">
          <CircularProgress size={18} />
          <Typography variant="body2" color="text.secondary">
            Loading patient series...
          </Typography>
        </Stack>
      ) : null}

      {!loading && error ? <Alert severity="error">{error}</Alert> : null}

      {!loading && !error && selectedSeries ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
          {selectedSeries.deleted ? (
            <Chip label="DELETED" color="error" variant="filled" size="small" />
          ) : null}
          <Chip
            label={selectedSeries.phase ?? selectedSeries.type.toUpperCase()}
            color="primary"
            variant="outlined"
            size="small"
          />
          <Chip
            label={selectedSeries.has_seg ? 'SEG' : 'No SEG'}
            color={selectedSeries.has_seg ? 'secondary' : 'default'}
            variant={selectedSeries.has_seg ? 'filled' : 'outlined'}
            size="small"
          />
          <Chip
            label={selectedSeries.type === 'voi' ? 'VOI' : 'NIfTI'}
            color={selectedSeries.type === 'voi' ? 'success' : 'default'}
            variant={selectedSeries.type === 'voi' ? 'filled' : 'outlined'}
            size="small"
          />
          {selectedSeries.group ? (
            <Chip label={`Group ${selectedSeries.group}`} size="small" variant="outlined" />
          ) : null}
          {selectedSeries.laterality ? (
            <Chip
              label={`Side ${selectedSeries.laterality}`}
              size="small"
              variant="outlined"
            />
          ) : null}
        </Stack>
      ) : null}

      {!loading && !error && !selectedSeries ? (
        <Box>
          <Typography variant="body2" color="text.secondary">
            No series are available for this patient.
          </Typography>
        </Box>
      ) : null}
    </Stack>
  )
}

export default SeriesSelector
