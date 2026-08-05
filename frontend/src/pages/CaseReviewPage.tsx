import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Snackbar,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react'
import { useNavigate, useParams } from '../services/router'

import BlendSlider from '../components/viewer/BlendSlider'
import LayerToggle from '../components/viewer/LayerToggle'
import MprRenderer from '../components/viewer/MprRenderer'
import OpacitySlider from '../components/viewer/OpacitySlider'
import SegmentationColorMap from '../components/viewer/SegmentationColorMap'
import WindowLevelControl from '../components/viewer/WindowLevelControl'
import {
  createDefaultLayerState,
  ensureLayerStateForLabels,
  getLayerStateEntry,
  getSegmentationColor,
  getSegmentationDefaultOpacity,
  getSegmentationLabel,
  layerColorsForLabels,
  layerOpacitiesForLabels,
  sortedLayerLabels,
  type LayerState,
} from '../components/viewer/segmentationPalette'
import { useSliceNavigation } from '../components/viewer/useSliceNavigation'
import { useWindowLevel } from '../components/viewer/useWindowLevel'
import {
  apiClient,
  getApiErrorMessage,
  type CaseInventoryRow,
  type CaseSummary,
  type MetadataSyncPreviewResponse,
  type PhaseDecision,
  type Scope,
  type SliceQuery,
  type VolumeInfo,
} from '../services/api'
import {
  resolveMprRendererMode,
  type MprRendererMode,
} from '../services/mprRendererConfig'

const PHASE_DECISIONS: PhaseDecision[] = ['NC', 'CMP', 'NP', 'DELAY']
const Surface3DView = lazy(() => import('../components/viewer/Surface3DView'))

function CaseReviewPage() {
  const { dsid = 'unknown-dataset', caseId = 'unknown-case' } = useParams<{
    dsid: string
    caseId: string
  }>()
  const navigate = useNavigate()
  const [caseList, setCaseList] = useState<CaseSummary[]>([])
  const [caseListError, setCaseListError] = useState<string | null>(null)
  const [inventoryState, setInventoryState] = useState<{
    caseId: string | null
    rows: CaseInventoryRow[]
    error: string | null
  }>({ caseId: null, rows: [], error: null })
  const [scope, setScope] = useState<Scope>('complete')
  const [selectedScanIdx, setSelectedScanIdx] = useState('')
  const [selectedSide, setSelectedSide] = useState('')
  const [overlayEnabled, setOverlayEnabled] = useState(true)
  const [surfaceBlend, setSurfaceBlend] = useState(0.75)
  const [phaseApplying, setPhaseApplying] = useState(false)
  const [metadataSyncState, setMetadataSyncState] = useState<{
    open: boolean
    loading: boolean
    applying: boolean
    preview: MetadataSyncPreviewResponse | null
    error: string | null
  }>({ open: false, loading: false, applying: false, preview: null, error: null })
  const [handleReloadTick, setHandleReloadTick] = useState(0)
  const [mprRendererMode, setMprRendererMode] = useState<MprRendererMode>(() =>
    resolveMprRendererMode(),
  )
  const [volumeRequest, setVolumeRequest] = useState<{
    key: string | null
    info: VolumeInfo | null
    error: string | null
  }>({ key: null, info: null, error: null })
  const [layerState, setLayerState] = useState<LayerState>(() => createDefaultLayerState())
  const [toastState, setToastState] = useState<{
    open: boolean
    severity: 'success' | 'warning' | 'error'
    message: string
  }>({ open: false, severity: 'success', message: '' })
  const handleRecoveryRequestedRef = useRef(false)
  const windowLevel = useWindowLevel()
  const refreshCaseList = useCallback(async () => {
    try {
      const response = await apiClient.listCases(dsid)
      setCaseList(response)
      setCaseListError(null)
    } catch (error) {
      setCaseList([])
      setCaseListError(getApiErrorMessage(error))
    }
  }, [dsid])
  const refreshInventory = useCallback(async () => {
    try {
      const response = await apiClient.listCaseInventory(dsid, caseId)
      setInventoryState({ caseId, rows: response, error: null })
    } catch (error) {
      setInventoryState({ caseId, rows: [], error: getApiErrorMessage(error) })
    }
  }, [caseId, dsid])
  const inventory = useMemo(
    () => (inventoryState.caseId === caseId ? inventoryState.rows : []),
    [caseId, inventoryState.caseId, inventoryState.rows],
  )
  const inventoryError = inventoryState.caseId === caseId ? inventoryState.error : null
  const inventoryLoading = inventoryState.caseId !== caseId

  useEffect(() => {
    void refreshCaseList()
  }, [refreshCaseList])

  useEffect(() => {
    let active = true

    apiClient
      .getHealth()
      .then((health) => {
        if (active) {
          setMprRendererMode(resolveMprRendererMode(health.mpr_renderer))
        }
      })
      .catch(() => {
        if (active) {
          setMprRendererMode(resolveMprRendererMode())
        }
      })

    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    setInventoryState({ caseId: null, rows: [], error: null })
    void refreshInventory()
  }, [caseId, refreshInventory])

  const scopedRows = useMemo(
    () => inventory.filter((row) => row.scope_availability[scope]),
    [inventory, scope],
  )
  const scanOptions = useMemo(
    () =>
      Array.from(new Set(scopedRows.map((row) => row.scan_idx ?? ''))).sort((left, right) =>
        left.localeCompare(right, undefined, { numeric: true }),
      ),
    [scopedRows],
  )
  const effectiveSelectedScanIdx = scanOptions.includes(selectedScanIdx)
    ? selectedScanIdx
    : scanOptions[0] ?? ''
  const scanRows = useMemo(
    () => scopedRows.filter((row) => (row.scan_idx ?? '') === effectiveSelectedScanIdx),
    [effectiveSelectedScanIdx, scopedRows],
  )
  const sideOptions = useMemo(
    () =>
      Array.from(new Set(scanRows.map((row) => row.side ?? '').filter(Boolean))).sort(),
    [scanRows],
  )
  const effectiveSelectedSide = sideOptions.includes(selectedSide)
    ? selectedSide
    : sideOptions[0] ?? ''

  useEffect(() => {
    if (scanOptions.length === 0) {
      setSelectedScanIdx('')
      return
    }
    if (!scanOptions.includes(selectedScanIdx)) {
      setSelectedScanIdx(scanOptions[0])
    }
  }, [scanOptions, selectedScanIdx])

  useEffect(() => {
    if (sideOptions.length === 0) {
      setSelectedSide('')
      return
    }
    if (!sideOptions.includes(selectedSide)) {
      setSelectedSide(sideOptions[0])
    }
  }, [sideOptions, selectedSide])

  const selectedRow = useMemo(() => {
    return (
      scanRows.find((row) => {
        const sideMatches =
          sideOptions.length === 0 || (row.side ?? '') === effectiveSelectedSide
        return sideMatches
      }) ?? scanRows[0] ?? null
    )
  }, [effectiveSelectedSide, scanRows, sideOptions.length])

  const selectedLoadKey = selectedRow
    ? `${selectedRow.row_index}:${selectedRow.row_id}:${scope}:${handleReloadTick}`
    : null

  useEffect(() => {
    if (!selectedRow) {
      setVolumeRequest({ key: null, info: null, error: null })
      return
    }
    const controller = new AbortController()
    let active = true
    apiClient
      .loadCaseSource(dsid, caseId, selectedRow.row_id, scope, selectedRow.row_index, {
        signal: controller.signal,
      })
      .then((info) => {
        if (!active) {
          return
        }
        handleRecoveryRequestedRef.current = false
        setVolumeRequest({ key: selectedLoadKey, info, error: null })
      })
      .catch((error) => {
        if (!active) {
          return
        }
        handleRecoveryRequestedRef.current = false
        setVolumeRequest({ key: selectedLoadKey, info: null, error: getApiErrorMessage(error) })
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [caseId, dsid, scope, selectedLoadKey, selectedRow])

  const activeVolumeInfo =
    selectedLoadKey && volumeRequest.key === selectedLoadKey ? volumeRequest.info : null
  const volumeError =
    selectedLoadKey && volumeRequest.key === selectedLoadKey ? volumeRequest.error : null
  const volumeLoading = Boolean(selectedRow) && volumeRequest.key !== selectedLoadKey
  const navigation = useSliceNavigation(activeVolumeInfo?.shape ?? null, selectedLoadKey)
  const activeLoadHandle = activeVolumeInfo?.load_handle ?? null
  const availableLabels = useMemo(() => activeVolumeInfo?.labels ?? [], [activeVolumeInfo?.labels])
  const sortedAvailableLabels = useMemo(() => sortedLayerLabels(availableLabels), [availableLabels])

  useEffect(() => {
    setLayerState((current) => ensureLayerStateForLabels(current, sortedAvailableLabels))
  }, [sortedAvailableLabels])

  const visibleLayers = useMemo(
    () =>
      overlayEnabled
        ? sortedAvailableLabels.filter((label) => getLayerStateEntry(layerState, label).visible)
        : [],
    [layerState, overlayEnabled, sortedAvailableLabels],
  )
  const layerOpacities = useMemo(
    () =>
      layerOpacitiesForLabels(
        sortedLayerLabels(Object.keys(layerState).map((label) => Number(label))),
        layerState,
      ),
    [layerState],
  )
  const surfaceLayerColors = useMemo(
    () => layerColorsForLabels(sortedAvailableLabels),
    [sortedAvailableLabels],
  )
  const sliceQuery: SliceQuery = {
    load_handle: activeLoadHandle ?? undefined,
    ww: windowLevel.ww,
    wl: windowLevel.wl,
    layers: visibleLayers,
    opacities: layerOpacities,
    opacity_1: getLayerStateEntry(layerState, 1).opacity,
    opacity_2: getLayerStateEntry(layerState, 2).opacity,
    opacity_3: getLayerStateEntry(layerState, 3).opacity,
  }
  const requestHandleReload = useCallback(() => {
    if (!selectedRow || handleRecoveryRequestedRef.current) {
      return
    }
    handleRecoveryRequestedRef.current = true
    setHandleReloadTick((current) => current + 1)
  }, [selectedRow])
  const selectedCase = caseList.find((entry) => entry.case_id === caseId) ?? null
  const currentPhase = selectedRow?.canonical_phase ?? null
  const selectedRowDeleted = Boolean(selectedRow?.deleted)
  const currentPhaseOutsideButtons = Boolean(
    currentPhase && !PHASE_DECISIONS.includes(currentPhase as PhaseDecision),
  )
  const applyPhaseChange = useCallback(
    async (targetPhase: PhaseDecision) => {
      if (
        !selectedRow?.series_id ||
        selectedRow.deleted ||
        phaseApplying ||
        scope === 'voi' ||
        selectedRow.canonical_phase === targetPhase
      ) {
        return
      }
      setPhaseApplying(true)
      try {
        const response = await apiClient.applyReviewOperations(dsid, {
          operations: [
            {
              patient_id: caseId,
              series_id: selectedRow.series_id,
              action: 'reclassify',
              target_phase: targetPhase,
            },
          ],
        })
        const result = response.results[0]
        if (response.summary.failed > 0 || result?.status !== 'applied') {
          setToastState({
            open: true,
            severity: 'error',
            message: result?.message ?? 'Phase was not applied.',
          })
          return
        }
        await Promise.all([refreshInventory(), refreshCaseList()])
        setHandleReloadTick((current) => current + 1)
        setToastState({
          open: true,
          severity: 'success',
          message: `Phase changed to ${targetPhase}.`,
        })
      } catch (error) {
        setToastState({
          open: true,
          severity: 'error',
          message: getApiErrorMessage(error),
        })
      } finally {
        setPhaseApplying(false)
      }
    },
    [caseId, dsid, phaseApplying, refreshCaseList, refreshInventory, scope, selectedRow],
  )
  const applySelectedScanDeletionState = useCallback(async () => {
    if (!selectedRow?.series_id || phaseApplying) {
      return
    }
    const action = selectedRow.deleted ? 'restore' : 'delete'
    setPhaseApplying(true)
    try {
      const response = await apiClient.applyReviewOperations(dsid, {
        operations: [
          {
            patient_id: caseId,
            series_id: selectedRow.series_id,
            action,
          },
        ],
      })
      const result = response.results[0]
      if (response.summary.failed > 0 || result?.status !== 'applied') {
        setToastState({
          open: true,
          severity: 'error',
          message:
            result?.message ??
            (action === 'restore'
              ? 'Scan was not restored from recycle bin.'
              : 'Scan was not moved to recycle bin.'),
        })
        return
      }
      await Promise.all([refreshInventory(), refreshCaseList()])
      setHandleReloadTick((current) => current + 1)
      setToastState({
        open: true,
        severity: 'success',
        message:
          action === 'restore'
            ? 'Scan restored from recycle bin.'
            : 'Scan moved to recycle bin.',
      })
    } catch (error) {
      setToastState({
        open: true,
        severity: 'error',
        message: getApiErrorMessage(error),
      })
    } finally {
      setPhaseApplying(false)
    }
  }, [caseId, dsid, phaseApplying, refreshCaseList, refreshInventory, selectedRow])

  const openMetadataSyncPreview = useCallback(async () => {
    setMetadataSyncState({
      open: true,
      loading: true,
      applying: false,
      preview: null,
      error: null,
    })
    try {
      const preview = await apiClient.previewMetadataSync(dsid)
      setMetadataSyncState({
        open: true,
        loading: false,
        applying: false,
        preview,
        error: null,
      })
    } catch (error) {
      setMetadataSyncState({
        open: true,
        loading: false,
        applying: false,
        preview: null,
        error: getApiErrorMessage(error),
      })
    }
  }, [dsid])

  const applyMetadataSync = useCallback(async () => {
    const preview = metadataSyncState.preview
    if (
      !preview ||
      preview.summary.conflicts > 0 ||
      metadataSyncActionableCount(preview) === 0 ||
      metadataSyncState.applying
    ) {
      return
    }
    setMetadataSyncState((current) => ({ ...current, applying: true, error: null }))
    try {
      const response = await apiClient.applyMetadataSync(dsid)
      await Promise.all([refreshInventory(), refreshCaseList()])
      setHandleReloadTick((current) => current + 1)
      setMetadataSyncState({
        open: false,
        loading: false,
        applying: false,
        preview: null,
        error: null,
      })
      setToastState({
        open: true,
        severity: 'success',
        message: `metadata.jsonl updated (${response.batch_id}).`,
      })
    } catch (error) {
      setMetadataSyncState((current) => ({
        ...current,
        applying: false,
        error: getApiErrorMessage(error),
      }))
    }
  }, [dsid, metadataSyncState.applying, metadataSyncState.preview, refreshCaseList, refreshInventory])

  const phaseButtonSx = useCallback(
    (phase: PhaseDecision) => {
      const active = currentPhase === phase
      return {
        borderRadius: 1,
        minWidth: 64,
        fontWeight: 700,
        ...(active
          ? {
              bgcolor: '#67d7ff',
              borderColor: '#67d7ff',
              color: '#05131d',
              '&:hover': {
                bgcolor: '#67d7ff',
                borderColor: '#67d7ff',
              },
            }
          : {
              color: 'text.primary',
              borderColor: 'divider',
            }),
      }
    },
    [currentPhase],
  )

  const surfacePanel = {
    caption: activeVolumeInfo?.has_mask
      ? availableLabels.length > 0
        ? 'Segmentation surface'
        : 'Empty segmentation mask'
      : 'No segmentation available',
    content: (
      <Stack spacing={0.75} sx={{ height: '100%', p: 0.5 }}>
        <Suspense
          fallback={
            <Stack alignItems="center" justifyContent="center" sx={{ flex: 1 }}>
              <Typography variant="body2" color="text.secondary">
                Loading 3D renderer...
              </Typography>
            </Stack>
          }
        >
          <Surface3DView
            availableLabels={availableLabels}
            blend={surfaceBlend}
            crosshairPoint={navigation.crosshairPoint}
            errorText={volumeError}
            hasMask={Boolean(activeVolumeInfo?.has_mask)}
            labelColors={surfaceLayerColors}
            loadHandle={activeLoadHandle}
            onHandleExpired={requestHandleReload}
            spacing={activeVolumeInfo?.spacing ?? null}
            visibleLabels={visibleLayers}
            volumeShape={activeVolumeInfo?.shape ?? null}
          />
        </Suspense>
        <BlendSlider
          disabled={!activeVolumeInfo?.has_mask || visibleLayers.length === 0}
          onChange={setSurfaceBlend}
          value={surfaceBlend}
        />
      </Stack>
    ),
  }

  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', xl: '280px minmax(0, 1fr) 320px' },
        gap: 2,
        alignItems: 'start',
      }}
    >
      <CaseRail
        cases={caseList}
        currentCaseId={caseId}
        error={caseListError}
        onSelect={(nextCaseId) => navigate(`/datasets/${dsid}/cases/${nextCaseId}/review`)}
      />

      <Stack spacing={2} sx={{ minWidth: 0 }}>
        <Paper elevation={0} sx={{ px: 2, py: 1.5 }}>
          <Stack spacing={1.5}>
            <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" useFlexGap>
              <Typography variant="h4" sx={{ mr: 1 }}>
                {caseId}
              </Typography>
              <Chip label={selectedCase?.patient_id ?? 'Unknown patient'} variant="outlined" />
              <Chip label={selectedCase?.group ?? 'Unknown group'} variant="outlined" />
              {activeVolumeInfo ? (
                <Chip label={`${activeVolumeInfo.shape.join(' x ')}`} size="small" variant="outlined" />
              ) : null}
              {volumeLoading ? <CircularProgress size={18} /> : null}
            </Stack>

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
              {PHASE_DECISIONS.map((phase) => (
                <Button
                  key={phase}
                  variant={currentPhase === phase ? 'contained' : 'outlined'}
                  size="small"
                  disabled={!selectedRow?.series_id || selectedRowDeleted || phaseApplying || scope === 'voi'}
                  onClick={() => void applyPhaseChange(phase)}
                  sx={phaseButtonSx(phase)}
                  data-testid="phase-button"
                >
                  {phase}
                </Button>
              ))}
              {currentPhaseOutsideButtons ? (
                <Button
                  variant="contained"
                  size="small"
                  sx={{
                    borderRadius: 1,
                    minWidth: 64,
                    fontWeight: 700,
                    bgcolor: '#67d7ff',
                    borderColor: '#67d7ff',
                    color: '#05131d',
                    pointerEvents: 'none',
                    '&:hover': {
                      bgcolor: '#67d7ff',
                      borderColor: '#67d7ff',
                    },
                  }}
                  data-testid="phase-button"
                >
                  {currentPhase}
                </Button>
              ) : null}
              {phaseApplying ? <CircularProgress size={18} /> : null}
              <Button
                variant="outlined"
                color={selectedRowDeleted ? undefined : 'error'}
                size="small"
                disabled={!selectedRow?.series_id || phaseApplying}
                onClick={() => void applySelectedScanDeletionState()}
                sx={{
                  borderRadius: 1,
                  fontWeight: 700,
                  ...(selectedRowDeleted
                    ? {
                        color: '#fb923c',
                        borderColor: 'rgba(251, 146, 60, 0.72)',
                        bgcolor: 'rgba(251, 146, 60, 0.2)',
                        '&:hover': {
                          borderColor: '#fdba74',
                          bgcolor: 'rgba(251, 146, 60, 0.28)',
                        },
                      }
                    : {}),
                }}
              >
                {selectedRowDeleted ? 'Restore' : 'Delete'}
              </Button>
              <Button
                variant="outlined"
                size="small"
                disabled={phaseApplying || metadataSyncState.loading || metadataSyncState.applying}
                onClick={() => void openMetadataSyncPreview()}
                sx={{ borderRadius: 1, fontWeight: 700 }}
              >
                Update metadata
              </Button>
            </Stack>

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
              <ToggleButtonGroup
                exclusive
                size="small"
                value={scope}
                onChange={(_, value: Scope | null) => {
                  if (value) {
                    setScope(value)
                  }
                }}
              >
                <ToggleButton value="complete">Complete</ToggleButton>
                <ToggleButton value="voi">VOI</ToggleButton>
              </ToggleButtonGroup>
              {scanOptions.length > 1 ? (
                <FormControl size="small" sx={{ minWidth: 120 }} data-testid="scan-idx-selector">
                  <InputLabel id="scan-idx-label">scan_idx</InputLabel>
                  <Select
                    labelId="scan-idx-label"
                    label="scan_idx"
                    value={effectiveSelectedScanIdx}
                    onChange={(event) => setSelectedScanIdx(event.target.value)}
                  >
                    {scanOptions.map((scanIdx) => (
                      <MenuItem key={scanIdx || 'blank'} value={scanIdx}>
                        {scanIdx || '-'}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              ) : null}
              {(scope === 'voi' && sideOptions.length > 0) || sideOptions.length > 1 ? (
                <FormControl size="small" sx={{ minWidth: 100 }} data-testid="side-selector">
                  <InputLabel id="side-label">Side</InputLabel>
                  <Select
                    labelId="side-label"
                    label="Side"
                    value={effectiveSelectedSide}
                    onChange={(event) => setSelectedSide(event.target.value)}
                  >
                    {sideOptions.map((side) => (
                      <MenuItem key={side} value={side}>
                        {side}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              ) : null}
            </Stack>
          </Stack>
        </Paper>

        {inventoryError ? <Alert severity="error">{inventoryError}</Alert> : null}
        {!inventoryError && !selectedRow && !inventoryLoading ? (
          <Alert severity="warning">No {scope.toUpperCase()} source is available for the selected scan.</Alert>
        ) : null}

        <MprRenderer
          errorText={volumeError}
          navigation={navigation}
          onHandleExpired={requestHandleReload}
          onWindowLevelDrag={windowLevel.applyDrag}
          query={sliceQuery}
          rendererMode={mprRendererMode}
          requestKey={activeLoadHandle}
          surfacePanel={surfacePanel}
          wl={windowLevel.wl}
          ww={windowLevel.ww}
        />
      </Stack>

      <Stack spacing={2} sx={{ minWidth: 0 }}>
        <ViewerControls
          availableLabels={availableLabels}
          layerState={layerState}
          overlayEnabled={overlayEnabled}
          setLayerState={setLayerState}
          setOverlayEnabled={setOverlayEnabled}
          windowLevel={windowLevel}
        />
      </Stack>

      <Snackbar
        autoHideDuration={4200}
        open={toastState.open}
        onClose={(_, reason) => {
          if (reason !== 'clickaway') {
            setToastState((current) => ({ ...current, open: false }))
          }
        }}
      >
        <Alert
          severity={toastState.severity}
          variant="filled"
          onClose={() => setToastState((current) => ({ ...current, open: false }))}
        >
          {toastState.message}
        </Alert>
      </Snackbar>
      <MetadataSyncDialog
        applying={metadataSyncState.applying}
        error={metadataSyncState.error}
        loading={metadataSyncState.loading}
        onApply={() => void applyMetadataSync()}
        onClose={() =>
          setMetadataSyncState({
            open: false,
            loading: false,
            applying: false,
            preview: null,
            error: null,
          })
        }
        open={metadataSyncState.open}
        preview={metadataSyncState.preview}
      />
    </Box>
  )
}

function MetadataSyncDialog({
  applying,
  error,
  loading,
  onApply,
  onClose,
  open,
  preview,
}: {
  applying: boolean
  error: string | null
  loading: boolean
  onApply: () => void
  onClose: () => void
  open: boolean
  preview: MetadataSyncPreviewResponse | null
}) {
  const actionable = preview ? metadataSyncActionableCount(preview) : 0
  const hasConflicts = Boolean(preview?.summary.conflicts)
  const visibleChanges =
    preview?.changes
      .filter((change) => change.kind !== 'already_consolidated')
      .slice(0, 8) ?? []

  return (
    <Dialog open={open} onClose={applying ? undefined : onClose} fullWidth maxWidth="md">
      <DialogTitle>Update metadata</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 0.5 }}>
          {loading ? (
            <Stack direction="row" spacing={1} alignItems="center">
              <CircularProgress size={18} />
              <Typography variant="body2" color="text.secondary">
                Checking metadata changes...
              </Typography>
            </Stack>
          ) : null}
          {error ? <Alert severity="error">{error}</Alert> : null}
          {preview ? (
            <>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip label={`Phase ${preview.summary.phase_changes}`} size="small" />
                <Chip label={`Delete ${preview.summary.delete_changes}`} size="small" />
                <Chip label={`Restore ${preview.summary.restore_changes}`} size="small" />
                <Chip label={`VOI ${preview.summary.voi_catalog_changes}`} size="small" />
                <Chip
                  color={preview.summary.conflicts ? 'error' : 'default'}
                  label={`Conflicts ${preview.summary.conflicts}`}
                  size="small"
                />
                <Chip label={`Consolidated ${preview.summary.already_consolidated}`} size="small" />
              </Stack>
              {hasConflicts ? (
                <Alert severity="error">
                  Resolve conflicts before updating metadata.jsonl.
                </Alert>
              ) : actionable === 0 ? (
                <Alert severity="info">No pending metadata changes.</Alert>
              ) : (
                <Alert severity="warning">
                  Confirming will rewrite metadata.jsonl and voi_catalog.jsonl when VOI paths changed.
                </Alert>
              )}
              {visibleChanges.length > 0 ? (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Type</TableCell>
                      <TableCell>Target</TableCell>
                      <TableCell>File</TableCell>
                      <TableCell>Change</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {visibleChanges.map((change, index) => (
                      <TableRow key={`${change.target}:${change.filename}:${index}`}>
                        <TableCell>{formatMetadataSyncKind(change.kind)}</TableCell>
                        <TableCell>{change.target}</TableCell>
                        <TableCell>{change.filename}</TableCell>
                        <TableCell>
                          {change.target_phase
                            ? `${change.current_phase ?? '-'} -> ${change.target_phase}`
                            : `${change.current_relative_path ?? '-'} -> ${
                                change.target_relative_path ?? '-'
                              }`}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : null}
            </>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button disabled={applying} onClick={onClose}>
          Cancel
        </Button>
        <Button
          disabled={loading || applying || !preview || hasConflicts || actionable === 0}
          onClick={onApply}
          variant="contained"
        >
          {applying ? 'Applying...' : 'Apply update'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function metadataSyncActionableCount(preview: MetadataSyncPreviewResponse): number {
  return (
    preview.summary.phase_changes +
    preview.summary.delete_changes +
    preview.summary.restore_changes
  )
}

function formatMetadataSyncKind(kind: string): string {
  switch (kind) {
    case 'phase_changes':
      return 'Phase'
    case 'delete_changes':
      return 'Delete'
    case 'restore_changes':
      return 'Restore'
    case 'conflicts':
      return 'Conflict'
    default:
      return kind
  }
}

function CaseRail({
  cases,
  currentCaseId,
  error,
  onSelect,
}: {
  cases: CaseSummary[]
  currentCaseId: string
  error: string | null
  onSelect: (caseId: string) => void
}) {
  return (
    <Paper elevation={0} sx={{ p: 1.5, maxHeight: { xl: 'calc(100vh - 150px)' }, overflow: 'auto' }}>
      <Stack spacing={1}>
        <Typography variant="overline" color="text.secondary">
          Worklist
        </Typography>
        {error ? <Alert severity="warning">{error}</Alert> : null}
        {cases.slice(0, 200).map((entry) => (
          <Button
            key={entry.case_id}
            onClick={() => onSelect(entry.case_id)}
            variant={entry.case_id === currentCaseId ? 'contained' : 'text'}
            sx={{ justifyContent: 'space-between', borderRadius: 1, px: 1 }}
          >
            <span>{entry.case_id}</span>
            <span>{entry.warning_count}</span>
          </Button>
        ))}
      </Stack>
    </Paper>
  )
}

function ViewerControls({
  availableLabels,
  layerState,
  overlayEnabled,
  setLayerState,
  setOverlayEnabled,
  windowLevel,
}: {
  availableLabels: number[]
  layerState: LayerState
  overlayEnabled: boolean
  setLayerState: Dispatch<SetStateAction<LayerState>>
  setOverlayEnabled: Dispatch<SetStateAction<boolean>>
  windowLevel: ReturnType<typeof useWindowLevel>
}) {
  const hasAvailableLabels = availableLabels.length > 0
  const controlLabels = hasAvailableLabels ? sortedLayerLabels(availableLabels) : [1, 2, 3]

  return (
    <Paper elevation={0} sx={{ p: 1.5 }}>
      <Stack spacing={1.5}>
        <WindowLevelControl
          activePreset={windowLevel.activePreset}
          maxHu={windowLevel.maxHu}
          minHu={windowLevel.minHu}
          ww={windowLevel.ww}
          wl={windowLevel.wl}
          onCustomRange={windowLevel.setWindowRange}
          onPreset={windowLevel.applyPreset}
        />
        <Stack direction="row" spacing={1.25} alignItems="center" justifyContent="space-between">
          <Typography variant="caption" color="text.secondary">
            Overlay
          </Typography>
          <Switch
            checked={overlayEnabled && hasAvailableLabels}
            disabled={!hasAvailableLabels}
            onChange={(event) => setOverlayEnabled(event.target.checked)}
            size="small"
            slotProps={{ input: { 'aria-label': 'Overlay' } }}
          />
        </Stack>
        <Divider />
        <Typography variant="caption" color="text.secondary">
          Mask Layers
        </Typography>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {controlLabels.map((label) => (
            <LayerToggle
              key={label}
              checked={availableLabels.includes(label) && getLayerStateEntry(layerState, label).visible}
              color={getSegmentationColor(label)}
              disabled={!availableLabels.includes(label)}
              label={getSegmentationLabel(label)}
              onChange={(checked) =>
                setLayerState((current) => ({
                  ...current,
                  [label]: {
                    ...(current[label] ?? {
                      visible: checked,
                      opacity: getSegmentationDefaultOpacity(label),
                    }),
                    visible: checked,
                  },
                }))
              }
            />
          ))}
        </Stack>
        <SegmentationColorMap labels={controlLabels} />
        {controlLabels.map((label) => (
          <OpacitySlider
            key={label}
            color={getSegmentationColor(label)}
            disabled={!availableLabels.includes(label) || !getLayerStateEntry(layerState, label).visible}
            label={getSegmentationLabel(label)}
            onChange={(value) =>
              setLayerState((current) => ({
                ...current,
                [label]: {
                  ...(current[label] ?? {
                    visible: true,
                    opacity: getSegmentationDefaultOpacity(label),
                  }),
                  opacity: value,
                },
              }))
            }
            value={getLayerStateEntry(layerState, label).opacity}
          />
        ))}
      </Stack>
    </Paper>
  )
}

export default CaseReviewPage
