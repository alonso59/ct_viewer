import {
  Alert,
  Box,
  Snackbar,
  Stack,
  Typography,
} from '@mui/material'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import CaseDataModal from '../components/clinical-review/CaseDataModal'
import HelpOverlay from '../components/clinical-review/HelpOverlay'
import LeftReviewPanel from '../components/clinical-review/LeftReviewPanel'
import MPRViewer2x2 from '../components/clinical-review/MPRViewer2x2'
import OverlayControlsPopover from '../components/clinical-review/OverlayControlsPopover'
import TopReviewBar from '../components/clinical-review/TopReviewBar'
import {
  LAYER_META,
  PANEL_ACCENTS,
  PHASE_PRIORITY,
  SURFACE_LAYER_COLORS,
  describeSlice,
  hasBlockingMissingSeg,
  latestDecisionForRow,
  sourceLabel,
} from '../components/clinical-review/reviewUi'
import type { OverlayMode } from '../components/clinical-review/OverlayControls'
import SliceSlider from '../components/viewer/SliceSlider'
import SliceView from '../components/viewer/SliceView'
import { useSliceNavigation } from '../components/viewer/useSliceNavigation'
import { useWindowLevel } from '../components/viewer/useWindowLevel'
import {
  apiClient,
  getApiErrorMessage,
  type Axis,
  type CanonicalPhase,
  type CaseDossier,
  type CaseInventoryRow,
  type CaseSummary,
  type CorrectionQueueResponse,
  type CurationDecision,
  type Scope,
  type SliceQuery,
  type VolumeInfo,
} from '../services/api'

const Surface3DView = lazy(() => import('../components/viewer/Surface3DView'))

type LayerState = Record<1 | 2 | 3, { visible: boolean; opacity: number }>
const VOI_DISPLAY_SPACING = [1, 1, 1]

function CaseReviewPage() {
  const { dsid = 'unknown-dataset', caseId: routeCaseId } = useParams<{
    dsid: string
    caseId?: string
  }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [caseList, setCaseList] = useState<CaseSummary[]>([])
  const [caseListError, setCaseListError] = useState<string | null>(null)
  const [queueRefreshTick, setQueueRefreshTick] = useState(0)
  const [queueState, setQueueState] = useState<{
    datasetId: string | null
    queue: CorrectionQueueResponse | null
    error: string | null
  }>({ datasetId: null, queue: null, error: null })
  const [inventoryState, setInventoryState] = useState<{
    caseId: string | null
    rows: CaseInventoryRow[]
    error: string | null
  }>({ caseId: null, rows: [], error: null })
  const [curationHistoryState, setCurationHistoryState] = useState<{
    caseId: string | null
    decisions: CurationDecision[]
    error: string | null
  }>({ caseId: null, decisions: [], error: null })
  const [dossier, setDossier] = useState<CaseDossier | null>(null)
  const [scope, setScope] = useState<Scope>('complete')
  const [selectedPhase, setSelectedPhase] = useState<CanonicalPhase | null>(null)
  const [selectedScanIdx, setSelectedScanIdx] = useState('')
  const [selectedSide, setSelectedSide] = useState('')
  const [overlayEnabled, setOverlayEnabled] = useState(true)
  const [overlayMode, setOverlayMode] = useState<OverlayMode>('filled')
  const [caseDataOpen, setCaseDataOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [surfaceBlend, setSurfaceBlend] = useState(0.75)
  const [handleReloadTick, setHandleReloadTick] = useState(0)
  const [volumeRequest, setVolumeRequest] = useState<{
    key: string | null
    info: VolumeInfo | null
    error: string | null
  }>({ key: null, info: null, error: null })
  const [layerState, setLayerState] = useState<LayerState>(() => ({
    1: { visible: true, opacity: LAYER_META[1].defaultOpacity },
    2: { visible: true, opacity: LAYER_META[2].defaultOpacity },
    3: { visible: false, opacity: LAYER_META[3].defaultOpacity },
  }))
  const [toastState, setToastState] = useState<{
    open: boolean
    severity: 'success' | 'warning' | 'error'
    message: string
  }>({ open: false, severity: 'success', message: '' })
  const handleRecoveryRequestedRef = useRef(false)
  const sourceParamsAppliedRef = useRef<string | null>(null)
  const windowLevel = useWindowLevel()

  const sortedCases = useMemo(
    () =>
      [...caseList].sort((left, right) =>
        left.case_id.localeCompare(right.case_id, undefined, {
          sensitivity: 'base',
          numeric: true,
        }),
      ),
    [caseList],
  )
  const caseId = routeCaseId ?? sortedCases[0]?.case_id ?? ''

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
    if (!caseId) {
      setInventoryState({ caseId: null, rows: [], error: null })
      return
    }
    try {
      const response = await apiClient.listCaseInventory(dsid, caseId)
      setInventoryState({ caseId, rows: response, error: null })
    } catch (error) {
      setInventoryState({ caseId, rows: [], error: getApiErrorMessage(error) })
    }
  }, [caseId, dsid])

  const refreshHistory = useCallback(async () => {
    if (!caseId) {
      setCurationHistoryState({ caseId: null, decisions: [], error: null })
      return
    }
    try {
      const response = await apiClient.getCurationHistory(dsid, caseId)
      setCurationHistoryState({ caseId, decisions: response, error: null })
    } catch (error) {
      setCurationHistoryState({
        caseId,
        decisions: [],
        error: getApiErrorMessage(error),
      })
    }
  }, [caseId, dsid])

  const refreshQueue = useCallback(async () => {
    try {
      const response = await apiClient.listCorrectionQueue(dsid)
      setQueueState({ datasetId: dsid, queue: response, error: null })
    } catch (error) {
      setQueueState({ datasetId: dsid, queue: null, error: getApiErrorMessage(error) })
    }
  }, [dsid])

  const inventory = useMemo(
    () => (inventoryState.caseId === caseId ? inventoryState.rows : []),
    [caseId, inventoryState.caseId, inventoryState.rows],
  )
  const curationHistory = useMemo(
    () =>
      curationHistoryState.caseId === caseId ? curationHistoryState.decisions : [],
    [caseId, curationHistoryState.caseId, curationHistoryState.decisions],
  )
  const curationHistoryError =
    curationHistoryState.caseId === caseId ? curationHistoryState.error : null
  const inventoryError = inventoryState.caseId === caseId ? inventoryState.error : null
  const inventoryLoading = inventoryState.caseId !== caseId
  const queueItems = queueState.datasetId === dsid ? queueState.queue?.items ?? [] : []
  const queuedCaseIds = useMemo(
    () => Array.from(new Set(queueItems.map((item) => item.case_id))),
    [queueItems],
  )

  useEffect(() => {
    void refreshCaseList()
  }, [refreshCaseList])

  useEffect(() => {
    if (!routeCaseId && sortedCases[0]) {
      navigate(`/datasets/${dsid}/review/${sortedCases[0].case_id}`, { replace: true })
    }
  }, [dsid, navigate, routeCaseId, sortedCases])

  useEffect(() => {
    void refreshQueue()
  }, [refreshQueue, queueRefreshTick])

  useEffect(() => {
    if (!caseId) {
      return
    }
    let active = true
    sourceParamsAppliedRef.current = null
    setInventoryState({ caseId: null, rows: [], error: null })
    setCurationHistoryState({ caseId: null, decisions: [], error: null })
    setDossier(null)
    void refreshInventory()
    void refreshHistory()

    apiClient
      .getCaseDossier(dsid, caseId)
      .then((response) => {
        if (active) {
          setDossier(response)
        }
      })
      .catch(() => {
        if (active) {
          setDossier(null)
        }
      })
    return () => {
      active = false
    }
  }, [caseId, dsid, refreshHistory, refreshInventory])

  const phases = useMemo(
    () =>
      Array.from(new Set(inventory.map((row) => row.canonical_phase))).sort(
        (left, right) => PHASE_PRIORITY.indexOf(left) - PHASE_PRIORITY.indexOf(right),
      ),
    [inventory],
  )

  useEffect(() => {
    if (phases.length === 0) {
      setSelectedPhase(null)
      return
    }
    if (selectedPhase && phases.includes(selectedPhase)) {
      return
    }
    const phaseWithComplete =
      phases.find((phase) =>
        inventory.some((row) => row.canonical_phase === phase && row.scope_availability.complete),
      ) ?? phases[0]
    setSelectedPhase(phaseWithComplete)
  }, [inventory, phases, selectedPhase])

  const phaseRows = useMemo(
    () =>
      inventory.filter(
        (row) => row.canonical_phase === selectedPhase && row.scope_availability[scope],
      ),
    [inventory, scope, selectedPhase],
  )
  const scanOptions = useMemo(
    () =>
      Array.from(new Set(phaseRows.map((row) => row.scan_idx ?? ''))).sort((left, right) =>
        left.localeCompare(right, undefined, { numeric: true }),
      ),
    [phaseRows],
  )
  const sideOptions = useMemo(
    () => Array.from(new Set(phaseRows.map((row) => row.side ?? '').filter(Boolean))).sort(),
    [phaseRows],
  )
  const sideSelectionActive = scope === 'voi' && sideOptions.length > 0

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

  useEffect(() => {
    const queryRowId = searchParams.get('row_id')
    const queryScope = normalizeScope(searchParams.get('scope'))
    const key = `${caseId}:${queryRowId ?? ''}:${queryScope ?? ''}`
    if (!queryRowId || inventory.length === 0 || sourceParamsAppliedRef.current === key) {
      return
    }
    const row = inventory.find((entry) => entry.row_id === queryRowId)
    if (!row) {
      sourceParamsAppliedRef.current = key
      return
    }
    const nextScope = queryScope && row.scope_availability[queryScope] ? queryScope : scope
    sourceParamsAppliedRef.current = key
    setScope(nextScope)
    setSelectedPhase(row.canonical_phase)
    setSelectedScanIdx(row.scan_idx ?? '')
    setSelectedSide(row.side ?? '')
  }, [caseId, inventory, scope, searchParams])

  const selectedRow = useMemo(() => {
    return (
      phaseRows.find((row) => {
        const scanMatches = (row.scan_idx ?? '') === selectedScanIdx
        const sideMatches =
          !sideSelectionActive || sideOptions.length === 0 || (row.side ?? '') === selectedSide
        return scanMatches && sideMatches
      }) ?? phaseRows[0] ?? null
    )
  }, [phaseRows, selectedScanIdx, selectedSide, sideOptions.length, sideSelectionActive])

  const selectedLoadKey = selectedRow ? `${selectedRow.row_id}:${scope}:${handleReloadTick}` : null

  useEffect(() => {
    if (!selectedRow) {
      setVolumeRequest({ key: null, info: null, error: null })
      return
    }
    const controller = new AbortController()
    let active = true
    apiClient
      .loadCaseSource(dsid, caseId, selectedRow.row_id, scope, {
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
  const viewerSpacing = scope === 'voi' ? VOI_DISPLAY_SPACING : activeVolumeInfo?.spacing
  const volumeLoading = Boolean(selectedRow) && volumeRequest.key !== selectedLoadKey
  const navigation = useSliceNavigation(activeVolumeInfo?.shape ?? null)
  const activeLoadHandle = activeVolumeInfo?.load_handle ?? null
  const availableLabels = useMemo(() => activeVolumeInfo?.labels ?? [], [activeVolumeInfo?.labels])
  const visibleLayers = useMemo(
    () =>
      overlayEnabled
        ? availableLabels.filter((label) => layerState[label as 1 | 2 | 3]?.visible)
        : [],
    [availableLabels, layerState, overlayEnabled],
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
  const requestHandleReload = useCallback(() => {
    if (!selectedRow || handleRecoveryRequestedRef.current) {
      return
    }
    handleRecoveryRequestedRef.current = true
    setHandleReloadTick((current) => current + 1)
  }, [selectedRow])

  const selectedCase = caseList.find((entry) => entry.case_id === caseId) ?? null
  const currentCaseIndex = sortedCases.findIndex((entry) => entry.case_id === caseId)
  const nextCase = currentCaseIndex >= 0 ? sortedCases[currentCaseIndex + 1] ?? null : null
  const caseWarningCount = inventory.reduce((total, row) => total + row.qc_warnings.length, 0)
  const selectedSourceLabel = sourceLabel(selectedRow, scope)
  const latestDecision = latestDecisionForRow(curationHistory, selectedRow?.row_id ?? null)
  const activeQcStatus =
    selectedRow?.latest_curation_status ??
    latestDecision?.status ??
    selectedCase?.latest_curation_status ??
    null
  const currentCaseQueued = queueItems.some((item) => item.case_id === caseId)
  const missingSegBlocked = hasBlockingMissingSeg(selectedRow)

  const handleSelectSource = useCallback((row: CaseInventoryRow, nextScope: Scope) => {
    setScope(nextScope)
    setSelectedPhase(row.canonical_phase)
    setSelectedScanIdx(row.scan_idx ?? '')
    setSelectedSide(row.side ?? '')
  }, [])

  const handleCurationSaved = useCallback(
    (decision: CurationDecision, queued: boolean, advance: boolean) => {
      setCurationHistoryState((current) =>
        current.caseId === caseId
          ? {
              ...current,
              decisions: [
                decision,
                ...current.decisions.filter((entry) => entry.review_id !== decision.review_id),
              ],
              error: null,
            }
          : current,
      )
      setInventoryState((current) =>
        current.caseId === caseId
          ? {
              ...current,
              rows: current.rows.map((row) =>
                row.row_id === decision.row_id
                  ? { ...row, latest_curation_status: decision.status }
                  : row,
              ),
            }
          : current,
      )
      setCaseList((current) =>
        current.map((entry) =>
          entry.case_id === caseId
            ? { ...entry, latest_curation_status: decision.status, has_comments: true }
            : entry,
        ),
      )
      if (queued) {
        setQueueRefreshTick((current) => current + 1)
        setQueueState((current) =>
          current.datasetId === dsid && current.queue
            ? {
                ...current,
                queue: {
                  ...current.queue,
                  items: [
                    decision,
                    ...current.queue.items.filter((item) => item.review_id !== decision.review_id),
                  ],
                },
              }
            : current,
        )
      }
      setToastState({
        open: true,
        severity: 'success',
        message: queued ? 'Decision saved and queued for correction.' : 'QC decision saved.',
      })
      void refreshHistory()
      void refreshInventory()
      void refreshCaseList()
      void refreshQueue()
      if (advance && nextCase) {
        navigate(`/datasets/${dsid}/review/${nextCase.case_id}`)
      }
    },
    [caseId, dsid, navigate, nextCase, refreshCaseList, refreshHistory, refreshInventory, refreshQueue],
  )

  const viewerPanels = {
    axial: {
      caption: describeSlice('axial', navigation.sliceIndices.axial, navigation.getMaxIndex('axial')),
      content: (
        <SlicePanel
          accent={PANEL_ACCENTS.axial}
          axis="axial"
          crosshair={navigation.getCrosshair('axial')}
          errorText={volumeError}
          fitLabel={scope === 'voi' ? 'VOI fit' : undefined}
          index={navigation.sliceIndices.axial}
          maxIndex={navigation.getMaxIndex('axial')}
          onCrosshairChange={(point) => navigation.setFromPanelPosition('axial', point)}
          onHandleExpired={requestHandleReload}
          onSliceChange={(index) => navigation.setSlice('axial', index)}
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
          fitLabel={scope === 'voi' ? 'VOI fit' : undefined}
          index={navigation.sliceIndices.sagittal}
          maxIndex={navigation.getMaxIndex('sagittal')}
          onCrosshairChange={(point) => navigation.setFromPanelPosition('sagittal', point)}
          onHandleExpired={requestHandleReload}
          onSliceChange={(index) => navigation.setSlice('sagittal', index)}
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
          fitLabel={scope === 'voi' ? 'VOI fit' : undefined}
          index={navigation.sliceIndices.coronal}
          maxIndex={navigation.getMaxIndex('coronal')}
          onCrosshairChange={(point) => navigation.setFromPanelPosition('coronal', point)}
          onHandleExpired={requestHandleReload}
          onSliceChange={(index) => navigation.setSlice('coronal', index)}
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
      caption: activeVolumeInfo?.has_mask ? 'Segmentation surface' : 'No segmentation available',
      content: (
        <Stack spacing={0} sx={{ height: '100%' }}>
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
              blend={surfaceBlend}
              errorText={volumeError}
              hasMask={Boolean(activeVolumeInfo?.has_mask)}
              labelColors={SURFACE_LAYER_COLORS}
              loadHandle={activeLoadHandle}
              onHandleExpired={requestHandleReload}
              visibleLabels={visibleLayers}
            />
          </Suspense>
        </Stack>
      ),
    },
  }

  return (
    <Stack
      data-testid="main-review-screen"
      spacing={1}
      sx={{
        height: { xs: 'auto', md: '100dvh' },
        minHeight: { xs: '100dvh', md: 0 },
        minWidth: 0,
        overflow: { xs: 'auto', md: 'hidden' },
        p: 1,
      }}
    >
      <TopReviewBar
        activeQcStatus={activeQcStatus}
        caseId={caseId || 'Loading case'}
        caseWarningCount={caseWarningCount}
        currentCaseQueued={currentCaseQueued}
        datasetId={dsid}
        onOpenHelp={() => setHelpOpen(true)}
        selectedCase={selectedCase}
        sourceLabel={selectedSourceLabel}
        volumeLoading={volumeLoading}
      />

      <Box
        data-testid="main-review-cockpit"
        sx={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: 'clamp(340px, 27vw, 480px) minmax(0, 1fr)' },
          gap: '2px',
          overflow: { xs: 'visible', md: 'hidden' },
        }}
      >
        <LeftReviewPanel
          caseError={caseListError}
          caseQueued={currentCaseQueued}
          cases={sortedCases}
          curationHistory={curationHistory}
          curationHistoryError={curationHistoryError}
          currentCaseId={caseId}
          datasetId={dsid}
          latestDecision={latestDecision}
          missingSegBlocked={missingSegBlocked}
          noSource={!selectedRow}
          onError={(message) =>
            setToastState({ open: true, severity: 'error', message })
          }
          onOpenCaseData={() => setCaseDataOpen(true)}
          onSaved={handleCurationSaved}
          onSelectCase={(nextCaseId) => navigate(`/datasets/${dsid}/review/${nextCaseId}`)}
          onSelectSource={handleSelectSource}
          queuedCaseIds={queuedCaseIds}
          rows={inventory}
          scope={scope}
          selectedCase={selectedCase}
          selectedPhase={selectedPhase}
          selectedRow={selectedRow}
          sourceLabel={selectedSourceLabel}
        />

        <Stack
          data-testid="viewer-workspace"
          spacing={0}
          sx={{ minWidth: 0, minHeight: 0, height: '100%', overflow: 'hidden' }}
        >
          {inventoryError ? <Alert severity="error">{inventoryError}</Alert> : null}
          {!inventoryError && !selectedRow && !inventoryLoading ? (
            <Alert severity="warning">No {scope.toUpperCase()} source is available.</Alert>
          ) : null}
          <Box
            data-testid="mpr-viewer-region"
            sx={{
              flex: 1,
              minHeight: 0,
              minWidth: 0,
              overflow: 'hidden',
              position: 'relative',
            }}
          >
            <MPRViewer2x2
              panels={viewerPanels}
            />
            <OverlayControlsPopover
              availableLabels={availableLabels}
              blend={surfaceBlend}
              blendDisabled={!activeVolumeInfo?.has_mask || visibleLayers.length === 0}
              layerState={layerState}
              mode={overlayMode}
              overlayEnabled={overlayEnabled}
              setBlend={setSurfaceBlend}
              setLayerState={setLayerState}
              setMode={setOverlayMode}
              setOverlayEnabled={setOverlayEnabled}
              visibleLabels={visibleLayers}
              windowLevel={windowLevel}
            />
          </Box>
          {/* BottomDrawer intentionally not rendered in v2.0 layout; content migrated to left module panel */}
        </Stack>
      </Box>

      <CaseDataModal
        caseSummary={selectedCase}
        decisions={curationHistory}
        dossier={dossier}
        onClose={() => setCaseDataOpen(false)}
        open={caseDataOpen}
        rows={inventory}
        selectedRow={selectedRow}
      />
      <HelpOverlay open={helpOpen} onClose={() => setHelpOpen(false)} />
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
          {queueState.error ? ` Queue status refresh warning: ${queueState.error}` : ''}
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
    <Stack spacing={0} sx={{ height: '100%', p: 0 }}>
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
        onHandleExpired={onHandleExpired}
        onSliceChange={onSliceChange}
        onWindowLevelDrag={onWindowLevelDrag}
        query={query}
        requestKey={requestKey}
        spacing={spacing}
        wl={wl}
        ww={ww}
      />
      <SliceSlider axis={axis} color={accent} index={index} maxIndex={maxIndex} onChange={onSliceChange} />
    </Stack>
  )
}

function normalizeScope(value: string | null): Scope | null {
  return value === 'complete' || value === 'voi' ? value : null
}

export default CaseReviewPage
