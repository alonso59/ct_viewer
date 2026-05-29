import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Snackbar,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom'

import {
  apiClient,
  type DatasetViewerSettings,
  type PatientSummary,
  type ReviewApplyResponse,
  type ReviewDeleteDecision,
  type ReviewOperation,
  getApiErrorMessage,
  type Axis,
  type PhaseDecision,
  type SeriesInfo,
  type SliceQuery,
  type VolumeInfo,
} from '../services/api'
import BlendSlider from '../components/viewer/BlendSlider'
import LayerToggle from '../components/viewer/LayerToggle'
import OpacitySlider from '../components/viewer/OpacitySlider'
import SeriesSelector from '../components/viewer/SeriesSelector'
import SliceSlider from '../components/viewer/SliceSlider'
import SliceView from '../components/viewer/SliceView'
import ViewerGrid2x2 from '../components/viewer/ViewerGrid2x2'
import WindowLevelControl from '../components/viewer/WindowLevelControl'
import { useSettings } from '../hooks/useSettings'
import { useSliceNavigation } from '../components/viewer/useSliceNavigation'
import { useWindowLevel } from '../components/viewer/useWindowLevel'

const PANEL_ACCENTS: Record<Axis, string> = {
  axial: '#fbbf24',
  coronal: '#ef4444',
  sagittal: '#22c55e',
}

const LAYER_META: Record<number, { label: string; color: string; defaultOpacity: number }> = {
  1: { label: 'Kidney', color: '#22d3ee', defaultOpacity: 0.15 },
  2: { label: 'Tumor', color: '#FFFF00', defaultOpacity: 0.2 },
  3: { label: 'Cyst', color: '#e879f9', defaultOpacity: 0.15 },
}

const SURFACE_LAYER_COLORS: Record<number, string> = {
  1: LAYER_META[1].color,
  2: LAYER_META[2].color,
  3: LAYER_META[3].color,
}
const VOI_DISPLAY_SPACING = [1, 1, 1]
const Surface3DView = lazy(() => import('../components/viewer/Surface3DView'))

function seriesKey(series: Pick<SeriesInfo, 'series_id' | 'storage_path'> | null): string | null {
  if (!series) {
    return null
  }
  return `${series.series_id}::${series.storage_path ?? ''}`
}

function mapLayerStateFromSettings(
  settings: DatasetViewerSettings,
): {
  1: { visible: boolean; opacity: number }
  2: { visible: boolean; opacity: number }
  3: { visible: boolean; opacity: number }
} {
  return {
    1: {
      visible: settings.layers_visible.includes(1),
      opacity: settings.layers_opacity['1'] ?? LAYER_META[1].defaultOpacity,
    },
    2: {
      visible: settings.layers_visible.includes(2),
      opacity: settings.layers_opacity['2'] ?? LAYER_META[2].defaultOpacity,
    },
    3: {
      visible: settings.layers_visible.includes(3),
      opacity: settings.layers_opacity['3'] ?? LAYER_META[3].defaultOpacity,
    },
  }
}

function ViewerPage() {
  const { dsid = 'unknown-dataset', pid = 'unknown-patient' } = useParams<{
    dsid: string
    pid: string
  }>()
  const navigate = useNavigate()

  const [hydratedDatasetId, setHydratedDatasetId] = useState<string | null>(null)
  const [selectedSeries, setSelectedSeries] = useState<SeriesInfo | null>(null)
  const [seriesList, setSeriesList] = useState<SeriesInfo[]>([])
  const [preferredSeriesId, setPreferredSeriesId] = useState<string | null>(null)
  const [volumeRequest, setVolumeRequest] = useState<{
    seriesKey: string | null
    info: VolumeInfo | null
    error: string | null
  }>({
    seriesKey: null,
    info: null,
    error: null,
  })
  const [layerState, setLayerState] = useState(() => ({
    1: { visible: true, opacity: LAYER_META[1].defaultOpacity },
    2: { visible: true, opacity: LAYER_META[2].defaultOpacity },
    3: { visible: false, opacity: LAYER_META[3].defaultOpacity },
  }))
  const [surfaceBlend, setSurfaceBlend] = useState(0.75)
  const [handleReloadTick, setHandleReloadTick] = useState(0)
  const reviewDataRevision = 0
  const [selectedGroup, setSelectedGroup] = useState('all')
  const [mutationsEnabled, setMutationsEnabled] = useState(false)
  const [deleteHistoryState, setDeleteHistoryState] = useState<{
    decisions: ReviewDeleteDecision[]
    error: string | null
    loading: boolean
  }>({
    decisions: [],
    error: null,
    loading: false,
  })
  const [applyState, setApplyState] = useState<{
    running: boolean
    error: string | null
    response: ReviewApplyResponse | null
  }>({
    running: false,
    error: null,
    response: null,
  })
  const [patientRequest, setPatientRequest] = useState<{
    datasetId: string | null
    patients: PatientSummary[]
    error: string | null
  }>({
    datasetId: null,
    patients: [],
    error: null,
  })
  const [toastState, setToastState] = useState<{
    open: boolean
    message: string
    severity: 'success' | 'warning' | 'error'
  }>({
    open: false,
    message: '',
    severity: 'success',
  })

  const handleRecoveryRequestedRef = useRef(false)
  const windowLevel = useWindowLevel()
  const settingsState = useSettings({
    datasetId: dsid,
    onLoadedDatasetSettings: (settings) => {
      setHydratedDatasetId(dsid)
      setPreferredSeriesId(settings.last_series)
      windowLevel.setWindowLevel(settings.ww ?? 400, settings.wl ?? 50)
      setLayerState(mapLayerStateFromSettings(settings))
    },
  })
  const {
    flushSettings,
    loadError: settingsLoadError,
    loading: settingsLoading,
    saveError: settingsSaveError,
    updateDatasetSettings,
  } = settingsState

  const selectedSeriesKey = seriesKey(selectedSeries)
  const activeVolumeInfo =
    selectedSeries && volumeRequest.seriesKey === selectedSeriesKey ? volumeRequest.info : null
  const volumeError =
    selectedSeries && volumeRequest.seriesKey === selectedSeriesKey ? volumeRequest.error : null
  const viewerSpacing =
    selectedSeries?.type === 'voi' ? VOI_DISPLAY_SPACING : activeVolumeInfo?.spacing
  const volumeLoading = selectedSeries !== null && volumeRequest.seriesKey !== selectedSeriesKey
  const selectedSeriesDeleted = Boolean(selectedSeries?.deleted)
  const navigation = useSliceNavigation(activeVolumeInfo?.shape ?? null)
  const activeLoadHandle = activeVolumeInfo?.load_handle ?? null
  const canPersistSettings =
    !settingsLoading &&
    (hydratedDatasetId === dsid || Boolean(settingsLoadError))

  const patientList = patientRequest.datasetId === dsid ? patientRequest.patients : []
  const patientLoading = patientRequest.datasetId !== dsid
  const patientError = patientRequest.datasetId === dsid ? patientRequest.error : null

  const groupOptions = useMemo(() => {
    const discovered = Array.from(
      new Set(patientList.map((patient) => normalizePatientGroup(patient.group))),
    ).sort((left, right) =>
      left.localeCompare(right, undefined, { sensitivity: 'base', numeric: true }),
    )
    return ['all', ...discovered]
  }, [patientList])

  const filteredPatients = useMemo(() => {
    return patientList
      .filter((patient) =>
        selectedGroup === 'all' ? true : normalizePatientGroup(patient.group) === selectedGroup,
      )
      .sort((left, right) =>
        left.patient_id.localeCompare(right.patient_id, undefined, {
          sensitivity: 'base',
          numeric: true,
        }),
      )
  }, [patientList, selectedGroup])
  const selectedPatientRecord = useMemo(
    () => filteredPatients.find((patient) => patient.patient_id === pid) ?? null,
    [filteredPatients, pid],
  )

  const currentPatientIndex = useMemo(
    () => filteredPatients.findIndex((patient) => patient.patient_id === pid),
    [filteredPatients, pid],
  )
  const previousPatient =
    currentPatientIndex > 0 ? filteredPatients[currentPatientIndex - 1] ?? null : null
  const nextPatient =
    currentPatientIndex >= 0 ? filteredPatients[currentPatientIndex + 1] ?? null : null
  const currentSeriesIndex = useMemo(
    () =>
      selectedSeries ? seriesList.findIndex((series) => seriesKey(series) === selectedSeriesKey) : -1,
    [selectedSeries, selectedSeriesKey, seriesList],
  )
  const previousSeries =
    currentSeriesIndex > 0 ? seriesList[currentSeriesIndex - 1] ?? null : null
  const nextSeries =
    currentSeriesIndex >= 0 ? seriesList[currentSeriesIndex + 1] ?? null : seriesList[0] ?? null
  const hasPreviousSeries =
    previousSeries !== null &&
    (selectedSeries === null || seriesKey(previousSeries) !== selectedSeriesKey)
  const hasNextSeries =
    nextSeries !== null &&
    (selectedSeries === null || seriesKey(nextSeries) !== selectedSeriesKey)
  const canRetreatReview = hasPreviousSeries || previousPatient !== null
  const canAdvanceReview = hasNextSeries || nextPatient !== null

  const requestHandleReload = useCallback(() => {
    if (!selectedSeries || handleRecoveryRequestedRef.current) {
      return
    }
    handleRecoveryRequestedRef.current = true
    setHandleReloadTick((current) => current + 1)
  }, [selectedSeries])

  useEffect(() => {
    let active = true

    apiClient
      .listPatients(dsid)
      .then((patients) => {
        if (!active) {
          return
        }
        setPatientRequest({
          datasetId: dsid,
          patients,
          error: null,
        })
      })
      .catch((requestError) => {
        if (!active) {
          return
        }
        setPatientRequest({
          datasetId: dsid,
          patients: [],
          error: getApiErrorMessage(requestError),
        })
      })

    return () => {
      active = false
    }
  }, [dsid, reviewDataRevision])

  useEffect(() => {
    if (selectedGroup === 'all') {
      return
    }
    if (!groupOptions.includes(selectedGroup)) {
      setSelectedGroup('all')
    }
  }, [groupOptions, selectedGroup])

  useEffect(() => {
    if (patientLoading || filteredPatients.length === 0) {
      return
    }
    if (filteredPatients.some((patient) => patient.patient_id === pid)) {
      return
    }
    navigate(`/datasets/${dsid}/patients/${filteredPatients[0].patient_id}/viewer`)
  }, [dsid, filteredPatients, navigate, patientLoading, pid])

  useEffect(() => {
    let active = true

    apiClient
      .getHealth()
      .then((health) => {
        if (active) {
          setMutationsEnabled(Boolean(health.allow_data_mutations))
        }
      })
      .catch(() => {
        if (active) {
          setMutationsEnabled(false)
        }
      })

    return () => {
      active = false
    }
  }, [])

  const loadDeleteHistory = useCallback(async () => {
    if (!mutationsEnabled) {
      setDeleteHistoryState({
        decisions: [],
        error: null,
        loading: false,
      })
      return
    }
    setDeleteHistoryState((current) => ({
      ...current,
      loading: true,
      error: null,
    }))
    try {
      const decisions = await apiClient.listDeleteDecisions(dsid)
      setDeleteHistoryState({
        decisions,
        error: null,
        loading: false,
      })
    } catch (requestError) {
      setDeleteHistoryState({
        decisions: [],
        error: getApiErrorMessage(requestError),
        loading: false,
      })
    }
  }, [dsid, mutationsEnabled])

  useEffect(() => {
    if (!selectedSeriesDeleted) {
      return
    }
    void loadDeleteHistory()
  }, [loadDeleteHistory, reviewDataRevision, selectedSeriesDeleted])

  useEffect(() => {
    if (!selectedSeries) {
      return
    }

    const controller = new AbortController()
    let active = true

    apiClient
      .loadSeries(dsid, pid, selectedSeries.series_id, selectedSeries.storage_path, {
        signal: controller.signal,
      })
      .then((info) => {
        if (!active) {
          return
        }
        handleRecoveryRequestedRef.current = false
        setVolumeRequest({
          seriesKey: selectedSeriesKey,
          info,
          error: null,
        })
      })
      .catch((requestError) => {
        if (!active) {
          return
        }
        handleRecoveryRequestedRef.current = false
        setVolumeRequest({
          seriesKey: selectedSeriesKey,
          info: null,
          error: getApiErrorMessage(requestError),
        })
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [dsid, handleReloadTick, pid, selectedSeries, selectedSeriesKey])

  useEffect(() => {
    function handleBeforeUnload() {
      void flushSettings().catch(() => {})
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [flushSettings])

  const availableLabels = activeVolumeInfo?.labels ?? []
  const visibleLayers = useMemo(
    () => availableLabels.filter((label) => layerState[label as 1 | 2 | 3]?.visible),
    [availableLabels, layerState],
  )
  const persistedVisibleLayers = useMemo(
    () => ([1, 2, 3] as const).filter((label) => layerState[label].visible),
    [layerState],
  )

  const sliceQuery: SliceQuery = {
    load_handle: activeLoadHandle ?? undefined,
    ww: windowLevel.ww,
    wl: windowLevel.wl,
    layers: visibleLayers,
    opacity_1: layerState[1].opacity,
    opacity_2: layerState[2].opacity,
    opacity_3: layerState[3].opacity,
  }

  useEffect(() => {
    if (!canPersistSettings) {
      return
    }

    updateDatasetSettings((current) => ({
      ...current,
      last_patient: pid,
      last_series: selectedSeries?.series_id ?? null,
      ww: windowLevel.ww,
      wl: windowLevel.wl,
      layers_visible: persistedVisibleLayers,
      layers_opacity: {
        1: layerState[1].opacity,
        2: layerState[2].opacity,
        3: layerState[3].opacity,
      },
    }))
  }, [
    layerState,
    persistedVisibleLayers,
    pid,
    selectedSeries?.series_id,
    canPersistSettings,
    dsid,
    hydratedDatasetId,
    updateDatasetSettings,
    windowLevel.wl,
    windowLevel.ww,
  ])

  async function applyReviewAction(
    _operation: ReviewOperation,
    _options?: {
      onSuccess?: () => void
    },
  ) {
    if (applyState.running) {
      return
    }
    setApplyState({
      running: false,
      error: 'Controlled dataset correction is disabled until Phase B.',
      response: null,
    })
    setToastState({
      open: true,
      severity: 'warning',
      message: 'Phase correction and file-moving actions are disabled until Phase B.',
    })
  }

  function reclassifyCurrentSeries(targetPhase: PhaseDecision) {
    if (!selectedSeries) {
      return
    }
    const nextSeriesId = hasNextSeries && nextSeries ? nextSeries.series_id : null
    const nextPatientId = !nextSeriesId && nextPatient ? nextPatient.patient_id : null
    void applyReviewAction(
      {
        patient_id: pid,
        series_id: selectedSeries.series_id,
        action: 'reclassify',
        target_phase: targetPhase,
      },
      {
        onSuccess: () => {
          if (nextSeriesId) {
            setPreferredSeriesId(nextSeriesId)
            return
          }
          if (nextPatientId) {
            void flushSettings().catch(() => {})
            navigate(`/datasets/${dsid}/patients/${nextPatientId}/viewer`)
          }
        },
      },
    )
  }

  function deleteCurrentSeries() {
    if (!selectedSeries) {
      return
    }
    void applyReviewAction({
      patient_id: pid,
      series_id: selectedSeries.series_id,
      action: 'delete',
    })
  }

  async function undoDelete(_decisionId: string) {
    if (applyState.running) {
      return
    }
    setApplyState({
      running: false,
      error: 'Controlled dataset correction is disabled until Phase B.',
      response: null,
    })
    setToastState({
      open: true,
      severity: 'warning',
      message: 'Undoing dataset file moves is disabled until Phase B.',
    })
  }

  async function undoCurrentSeriesDelete() {
    if (!selectedSeries || !selectedSeries.deleted || applyState.running) {
      return
    }
    const decisions =
      deleteHistoryState.decisions.length > 0
        ? deleteHistoryState.decisions
        : await apiClient.listDeleteDecisions(dsid)
    const matchingDecision = decisions.find(
      (decision) =>
        decision.patient_id === selectedSeries.patient_id &&
        decision.series_id === selectedSeries.series_id,
    )
    if (!matchingDecision) {
      setToastState({
        open: true,
        severity: 'warning',
        message: 'No delete record was found for the selected series.',
      })
      return
    }
    await undoDelete(matchingDecision.decision_id)
    setPreferredSeriesId(selectedSeries.series_id)
  }

  function clearTransientApplyState() {
    setApplyState((current) => ({ ...current, response: null, error: null }))
  }

  function handleSeriesSelection(nextSeries: SeriesInfo | null) {
    if (seriesKey(nextSeries) === selectedSeriesKey) {
      return
    }
    if (selectedSeriesKey) {
      void flushSettings().catch(() => {})
    }
    setSelectedSeries(nextSeries)
    clearTransientApplyState()
  }

  function goToNextSeries() {
    if (hasNextSeries && nextSeries) {
      void flushSettings().catch(() => {})
      setPreferredSeriesId(nextSeries.series_id)
      setSelectedSeries(nextSeries)
      clearTransientApplyState()
      return
    }
    if (nextPatient) {
      void flushSettings().catch(() => {})
      navigate(`/datasets/${dsid}/patients/${nextPatient.patient_id}/viewer`)
    }
  }

  function goToPreviousSeries() {
    if (hasPreviousSeries && previousSeries) {
      void flushSettings().catch(() => {})
      setPreferredSeriesId(previousSeries.series_id)
      setSelectedSeries(previousSeries)
      clearTransientApplyState()
      return
    }
    if (previousPatient) {
      void flushSettings().catch(() => {})
      navigate(`/datasets/${dsid}/patients/${previousPatient.patient_id}/viewer`)
    }
  }

  function getPhaseButtonSx(phase: PhaseDecision) {
    const isActive = selectedSeries?.phase === phase
    const baseSx = {
      transition: 'none',
    }
    if (!isActive) {
      return baseSx
    }
    return {
      ...baseSx,
      backgroundColor: alpha('#60a5fa', 0.3),
      borderColor: '#60a5fa',
      boxShadow: `0 0 0 1px ${alpha('#60a5fa', 0.35)} inset`,
      '&:hover': {
        backgroundColor: alpha('#60a5fa', 0.38),
        borderColor: '#93c5fd',
      },
    }
  }

  const viewerPanels = {
    axial: {
      caption: describeSlice('axial', navigation.sliceIndices.axial, navigation.getMaxIndex('axial')),
      content: (
        <SlicePanel
          accent={PANEL_ACCENTS.axial}
          axis="axial"
          crosshair={navigation.getCrosshair('axial')}
          errorText={volumeError}
          fitLabel={selectedSeries?.type === 'voi' ? 'VOI fit' : undefined}
          index={navigation.sliceIndices.axial}
          maxIndex={navigation.getMaxIndex('axial')}
          onCrosshairChange={(point) => navigation.setFromPanelPosition('axial', point)}
          onSliceChange={(index) => navigation.setSlice('axial', index)}
          onHandleExpired={requestHandleReload}
          onWindowLevelDrag={windowLevel.applyDrag}
          query={sliceQuery}
          requestKey={activeLoadHandle}
          spacing={viewerSpacing}
          wl={windowLevel.wl}
          ww={windowLevel.ww}
        />
      ),
    },
    coronal: {
      caption: describeSlice(
        'coronal',
        navigation.sliceIndices.coronal,
        navigation.getMaxIndex('coronal'),
      ),
      content: (
        <SlicePanel
          accent={PANEL_ACCENTS.coronal}
          axis="coronal"
          crosshair={navigation.getCrosshair('coronal')}
          errorText={volumeError}
          fitLabel={selectedSeries?.type === 'voi' ? 'VOI fit' : undefined}
          index={navigation.sliceIndices.coronal}
          maxIndex={navigation.getMaxIndex('coronal')}
          onCrosshairChange={(point) => navigation.setFromPanelPosition('coronal', point)}
          onSliceChange={(index) => navigation.setSlice('coronal', index)}
          onHandleExpired={requestHandleReload}
          onWindowLevelDrag={windowLevel.applyDrag}
          query={sliceQuery}
          requestKey={activeLoadHandle}
          spacing={viewerSpacing}
          wl={windowLevel.wl}
          ww={windowLevel.ww}
        />
      ),
    },
    sagittal: {
      caption: describeSlice(
        'sagittal',
        navigation.sliceIndices.sagittal,
        navigation.getMaxIndex('sagittal'),
      ),
      content: (
        <SlicePanel
          accent={PANEL_ACCENTS.sagittal}
          axis="sagittal"
          crosshair={navigation.getCrosshair('sagittal')}
          errorText={volumeError}
          fitLabel={selectedSeries?.type === 'voi' ? 'VOI fit' : undefined}
          index={navigation.sliceIndices.sagittal}
          maxIndex={navigation.getMaxIndex('sagittal')}
          onCrosshairChange={(point) => navigation.setFromPanelPosition('sagittal', point)}
          onSliceChange={(index) => navigation.setSlice('sagittal', index)}
          onHandleExpired={requestHandleReload}
          onWindowLevelDrag={windowLevel.applyDrag}
          query={sliceQuery}
          requestKey={activeLoadHandle}
          spacing={viewerSpacing}
          wl={windowLevel.wl}
          ww={windowLevel.ww}
        />
      ),
    },
    surface: {
      caption: activeVolumeInfo?.has_mask
        ? 'Interactive segmentation surface'
        : 'No segmentation available',
      content: (
        <Stack
          spacing={0.75}
          sx={{
            height: '100%',
            p: 0.5,
            background: 'transparent',
          }}
        >
          <Suspense
            fallback={
              <Stack
                spacing={1}
                alignItems="center"
                justifyContent="center"
                sx={{ flex: 1 }}
              >
                <Typography variant="body2" color="text.secondary">
                  Loading 3D renderer...
                </Typography>
              </Stack>
            }
          >
            <Surface3DView
              blend={surfaceBlend}
              errorText={volumeError}
              hasMask={Boolean(activeVolumeInfo?.has_mask)}
              labelColors={SURFACE_LAYER_COLORS}
              loadHandle={activeLoadHandle}
              onHandleExpired={requestHandleReload}
              visibleLabels={visibleLayers}
            />
          </Suspense>
          <Typography variant="caption" color="text.secondary">
            Visible 3D labels: {visibleLayers.length > 0 ? visibleLayers.join(', ') : 'none'}
          </Typography>
        </Stack>
      ),
    },
  }

  const sidebarContent = (
    <Paper
      elevation={0}
      sx={{
        px: { xs: 2.25, md: 2.5 },
        py: { xs: 2.25, md: 2.5 },
      }}
    >
      <Stack spacing={2}>
        <Stack
          direction={{ xs: 'column', sm: 'row', lg: 'column' }}
          spacing={1}
          justifyContent="flex-end"
        >
          <Button
            component={RouterLink}
            to={`/datasets/${dsid}/patients`}
            variant="outlined"
            size="small"
          >
            Back to Patient List
          </Button>
          <Button component={RouterLink} to="/" variant="contained" size="small">
            Return Home
          </Button>
        </Stack>

        <Stack spacing={1}>
          <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: '0.22em' }}>
            Legacy Technical Viewer
          </Typography>
          <Typography variant="h4" sx={{ lineHeight: 1.05 }}>
            {pid}
          </Typography>
          <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
            <Chip label={dsid} color="primary" variant="outlined" size="small" />
            <Chip
              label={selectedSeries?.filename ?? 'Select a series'}
              color={selectedSeriesDeleted ? 'error' : 'default'}
              variant={selectedSeriesDeleted ? 'filled' : 'outlined'}
              size="small"
            />
            {activeVolumeInfo ? (
              <Chip
                label={`${activeVolumeInfo.shape.join(' × ')}`}
                variant="outlined"
                size="small"
              />
            ) : null}
            {selectedPatientRecord?.has_deleted ? (
              <Chip
                label={`Deleted ${selectedPatientRecord.deleted_series_count}`}
                color="error"
                variant="filled"
                size="small"
              />
            ) : null}
          </Stack>
        </Stack>

        <Stack spacing={1.25}>
          <Stack direction={{ xs: 'column', sm: 'row', lg: 'column' }} spacing={1}>
            <FormControl fullWidth>
              <InputLabel id="viewer-group-filter-label">Group</InputLabel>
              <Select
                labelId="viewer-group-filter-label"
                label="Group"
                value={selectedGroup}
                onChange={(event) => setSelectedGroup(event.target.value)}
                disabled={patientLoading || groupOptions.length === 0}
              >
                {groupOptions.map((group) => (
                  <MenuItem key={group} value={group}>
                    {group === 'all' ? 'All' : group}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl fullWidth>
              <InputLabel id="viewer-patient-selector-label">Patient</InputLabel>
              <Select
                labelId="viewer-patient-selector-label"
                label="Patient"
                value={filteredPatients.some((patient) => patient.patient_id === pid) ? pid : ''}
                renderValue={(value) => {
                  const patient =
                    filteredPatients.find((entry) => entry.patient_id === value) ?? null
                  if (!patient) {
                    return ''
                  }
                  return patient.has_deleted
                    ? `${patient.patient_id} [DELETED ${patient.deleted_series_count}]`
                    : patient.patient_id
                }}
                onChange={(event) => {
                  void flushSettings().catch(() => {})
                  navigate(`/datasets/${dsid}/patients/${event.target.value}/viewer`)
                }}
                disabled={patientLoading || filteredPatients.length === 0}
              >
                {filteredPatients.map((patient) => (
                  <MenuItem key={patient.patient_id} value={patient.patient_id}>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
                      <Typography color={patient.has_deleted ? 'error.main' : 'text.primary'}>
                        {patient.patient_id}
                      </Typography>
                      {patient.has_deleted ? (
                        <Chip
                          label={`DELETED ${patient.deleted_series_count}`}
                          size="small"
                          color="error"
                          variant="filled"
                        />
                      ) : null}
                    </Stack>
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>

          <SeriesSelector
            datasetId={dsid}
            patientId={pid}
            onSeriesChange={handleSeriesSelection}
            onSeriesListLoaded={setSeriesList}
            preferredSeriesId={preferredSeriesId}
            reloadKey={reviewDataRevision}
          />
        </Stack>

        <Stack spacing={0.9}>
          <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: '0.22em' }}>
            Visible Masks
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
        </Stack>

        <Divider />

        <Stack
          spacing={1.5}
          sx={{
            '& .MuiChip-root': {
              height: 24,
            },
            '& .MuiFormControl-root .MuiInputBase-root': {
              minHeight: 44,
            },
            '& [data-window-width] .MuiButton-root': {
              py: 0.45,
            },
          }}
        >
          <WindowLevelControl
            ww={windowLevel.ww}
            wl={windowLevel.wl}
            onPreset={windowLevel.applyPreset}
          />
          <Stack spacing={1.2}>
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
            <BlendSlider
              disabled={!activeVolumeInfo?.has_mask || visibleLayers.length === 0}
              onChange={setSurfaceBlend}
              value={surfaceBlend}
            />
          </Stack>
        </Stack>

        {!mutationsEnabled ? (
          <Alert severity="info">
            Review actions are in read-only mode. Restart the backend with <code>ALLOW_DATA_MUTATIONS=true</code> to enable reclassify and delete.
          </Alert>
        ) : null}

        {patientError ? (
          <Alert severity="warning">Failed to load patient list: {patientError}</Alert>
        ) : null}
        {settingsLoadError ? (
          <Alert severity="warning">
            Failed to load dataset viewer settings: {settingsLoadError}
          </Alert>
        ) : null}
        {settingsSaveError ? (
          <Alert severity="warning">
            Failed to persist dataset viewer settings: {settingsSaveError}
          </Alert>
        ) : null}
      </Stack>
    </Paper>
  )

  return (
    <Stack spacing={3}>
      <Box
        sx={{
          display: 'grid',
          gap: { xs: 2, xl: 2.25 },
          gridTemplateColumns: {
            xs: 'minmax(0, 1fr)',
            xl: 'minmax(0, 1fr) minmax(300px, 340px)',
          },
          alignItems: 'start',
        }}
      >
        <Stack spacing={3} sx={{ minWidth: 0 }}>
          <Paper
            elevation={0}
            sx={{
              px: { xs: 2.25, md: 3 },
              py: { xs: 1.5, md: 1.75 },
            }}
          >
            <Stack
              direction={{ xs: 'column', xl: 'row' }}
              spacing={1.25}
              alignItems={{ xl: 'center' }}
              justifyContent="space-between"
            >
              <Stack
                direction={{ xs: 'column', lg: 'row' }}
                spacing={1.25}
                alignItems={{ lg: 'center' }}
                divider={
                  <Divider
                    orientation="vertical"
                    flexItem
                    sx={{ display: { xs: 'none', lg: 'block' }, borderColor: 'divider' }}
                  />
                }
              >
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Button
                    variant="outlined"
                    color="error"
                    onClick={deleteCurrentSeries}
                    disabled={!selectedSeries || selectedSeriesDeleted || applyState.running || !mutationsEnabled}
                    disableRipple
                    size="small"
                    sx={{ transition: 'none' }}
                  >
                    Delete
                  </Button>
                  <Button
                    variant="outlined"
                    onClick={() => {
                      if (selectedSeriesDeleted) {
                        void undoCurrentSeriesDelete()
                      }
                    }}
                    disabled={
                      applyState.running ||
                      !mutationsEnabled ||
                      !selectedSeriesDeleted
                    }
                    disableRipple
                    size="small"
                    sx={{
                      transition: 'none',
                      color: '#fb923c',
                      borderColor: alpha('#fb923c', 0.72),
                      backgroundColor: selectedSeriesDeleted ? alpha('#fb923c', 0.2) : 'transparent',
                      '&:hover': {
                        borderColor: '#fdba74',
                        backgroundColor: alpha('#fb923c', 0.28),
                      },
                    }}
                  >
                    Undo
                  </Button>
                </Stack>

                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Button
                    variant="outlined"
                    onClick={() => reclassifyCurrentSeries('NC')}
                    disabled={!selectedSeries || selectedSeriesDeleted || applyState.running || !mutationsEnabled}
                    disableRipple
                    size="small"
                    sx={getPhaseButtonSx('NC')}
                  >
                    NC
                  </Button>
                  <Button
                    variant="outlined"
                    onClick={() => reclassifyCurrentSeries('ART')}
                    disabled={!selectedSeries || selectedSeriesDeleted || applyState.running || !mutationsEnabled}
                    disableRipple
                    size="small"
                    sx={getPhaseButtonSx('ART')}
                  >
                    ART
                  </Button>
                  <Button
                    variant="outlined"
                    onClick={() => reclassifyCurrentSeries('VEN')}
                    disabled={!selectedSeries || selectedSeriesDeleted || applyState.running || !mutationsEnabled}
                    disableRipple
                    size="small"
                    sx={getPhaseButtonSx('VEN')}
                  >
                    VEN
                  </Button>
                </Stack>

                <Stack direction="row" spacing={1.25} flexWrap="wrap" useFlexGap>
                  <Tooltip title="Go to the previous series for the current patient">
                    <span>
                      <Button
                        variant="outlined"
                        onClick={goToPreviousSeries}
                        disabled={!canRetreatReview || applyState.running || volumeLoading || patientLoading}
                        disableRipple
                        size="small"
                        sx={{
                          transition: 'none',
                          color: '#cbd5e1',
                          borderColor: alpha('#94a3b8', 0.6),
                          backgroundColor: alpha('#94a3b8', 0.08),
                          '&:hover': {
                            borderColor: '#cbd5e1',
                            backgroundColor: alpha('#94a3b8', 0.16),
                          },
                          '&.Mui-disabled': {
                            color: alpha('#cbd5e1', 0.4),
                            borderColor: alpha('#94a3b8', 0.24),
                            backgroundColor: alpha('#94a3b8', 0.04),
                          },
                        }}
                      >
                        Back
                      </Button>
                    </span>
                  </Tooltip>
                  <Tooltip title="Go to the next series for the current patient">
                    <span>
                      <Button
                        variant="contained"
                        onClick={goToNextSeries}
                        disabled={!canAdvanceReview || applyState.running || volumeLoading || patientLoading}
                        disableRipple
                        size="small"
                        sx={{
                          transition: 'none',
                          backgroundColor: '#22c55e',
                          color: '#03130a',
                          '&:hover': {
                            backgroundColor: '#4ade80',
                          },
                          '&.Mui-disabled': {
                            backgroundColor: alpha('#22c55e', 0.2),
                            color: alpha('#d1fae5', 0.45),
                          },
                        }}
                      >
                        Next
                      </Button>
                    </span>
                  </Tooltip>
                </Stack>
              </Stack>
            </Stack>
          </Paper>

          <ViewerGrid2x2 panels={viewerPanels} />
        </Stack>

        <Box
          sx={{
            minWidth: 0,
            position: { xs: 'static', xl: 'sticky' },
            top: { xl: 18 },
            alignSelf: 'start',
          }}
        >
          {sidebarContent}
        </Box>
      </Box>

      <Snackbar
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
        autoHideDuration={4200}
        open={toastState.open}
        onClose={(_, reason) => {
          if (reason === 'clickaway') {
            return
          }
          setToastState((current) => ({ ...current, open: false }))
        }}
        sx={{ mt: 1.5, mr: 1.5 }}
      >
        <Alert
          severity={toastState.severity}
          variant="filled"
          elevation={6}
          onClose={() => setToastState((current) => ({ ...current, open: false }))}
          sx={{
            minWidth: 320,
            maxWidth: 520,
            borderRadius: 2.5,
            boxShadow: '0 18px 40px rgba(0,0,0,0.35)',
          }}
        >
          {toastState.message}
        </Alert>
      </Snackbar>
    </Stack>
  )
}

function SlicePanel({
  accent,
  axis,
  crosshair,
  errorText,
  fitLabel,
  index,
  maxIndex,
  onCrosshairChange,
  onSliceChange,
  onHandleExpired,
  onWindowLevelDrag,
  query,
  requestKey,
  spacing,
  wl,
  ww,
}: {
  accent: string
  axis: Axis
  crosshair: { x: number; y: number }
  errorText: string | null
  fitLabel?: string
  index: number
  maxIndex: number
  onCrosshairChange: (point: { x: number; y: number }) => void
  onSliceChange: (index: number) => void
  onHandleExpired: () => void
  onWindowLevelDrag: (
    startWw: number,
    startWl: number,
    deltaX: number,
    deltaY: number,
  ) => void
  query: SliceQuery
  requestKey: string | null
  spacing?: number[]
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
        fitLabel={fitLabel}
        index={index}
        maxIndex={maxIndex}
        onCrosshairChange={onCrosshairChange}
        onSliceChange={onSliceChange}
        onHandleExpired={onHandleExpired}
        onWindowLevelDrag={onWindowLevelDrag}
        query={query}
        requestKey={requestKey}
        spacing={spacing}
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

function normalizePatientGroup(group: string | null): string {
  const normalized = group?.trim()
  if (!normalized) {
    return 'Unknown'
  }
  return normalized
}

function describeSlice(axis: string, index: number, maxIndex: number) {
  return `${axis.toUpperCase()} ${index + 1} / ${maxIndex + 1}`
}

export default ViewerPage
