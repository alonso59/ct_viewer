import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MainReviewScreen from './MainReviewScreen'
import { apiClient, type CurationDecision } from '../services/api'

vi.mock('../components/viewer/SliceView', () => ({
  default: (props: { axis: string; fitLabel?: string; spacing?: number[] }) => (
    <div
      data-axis={props.axis}
      data-fit-label={props.fitLabel ?? ''}
      data-spacing={props.spacing?.join(',') ?? ''}
      data-testid="slice-view"
    >
      Slice
    </div>
  ),
}))

vi.mock('../components/viewer/Surface3DView', () => ({
  default: () => <div data-testid="surface-view">Surface</div>,
}))

vi.mock('../services/api', async () => {
  const apiClient = {
    getCaseDossier: vi.fn(),
    getCurationHistory: vi.fn(),
    listCases: vi.fn(),
    listCaseInventory: vi.fn(),
    listCorrectionQueue: vi.fn(),
    loadCaseSource: vi.fn(),
    saveCurationDecision: vi.fn(),
  }
  return {
    apiClient,
    getApiErrorMessage: (error: unknown) =>
      error instanceof Error ? error.message : 'Unexpected API error',
    isHandleExpiredError: () => false,
  }
})

const mockedApi = vi.mocked(apiClient)

const cases = [
  {
    case_id: 'case_00001',
    patient_id: 'patient-a',
    group: 'G',
    available_phases: ['NP', 'CMP'],
    scan_count: 2,
    seg_count: 1,
    voi_image_count: 2,
    voi_mask_count: 2,
    voi_sides: ['L', 'R'],
    latest_curation_status: null,
    warning_count: 2,
    has_comments: true,
  },
  {
    case_id: 'case_00002',
    patient_id: 'patient-b',
    group: 'G',
    available_phases: ['NP'],
    scan_count: 1,
    seg_count: 1,
    voi_image_count: 1,
    voi_mask_count: 1,
    voi_sides: ['L'],
    latest_curation_status: null,
    warning_count: 0,
    has_comments: false,
  },
]

const inventory = [
  {
    row_id: 'row-a',
    source_row_id: null,
    case_id: 'case_00001',
    patient_id: 'patient-a',
    group: 'G',
    raw_phase: 'ven',
    canonical_phase: 'NP',
    phase_status: 'normalized',
    scan_idx: '0',
    side: 'L',
    scope_availability: { complete: true, voi: true },
    nifti_path: { raw: 'nifti/a.nii.gz', resolved: '/data/nifti/a.nii.gz', status: 'exists' },
    seg_path: { raw: 'seg/a.nii.gz', resolved: '/data/seg/a.nii.gz', status: 'exists' },
    voi_image_path: { raw: 'voi/a_L.npy', resolved: '/data/voi/a_L.npy', status: 'exists' },
    voi_mask_path: { raw: 'voi/a_L.npy', resolved: '/data/voi/a_L.npy', status: 'exists' },
    has_seg: true,
    has_voi_image: true,
    has_voi_mask: true,
    qc_warnings: [],
    latest_curation_status: null,
  },
  {
    row_id: 'row-a-r',
    source_row_id: null,
    case_id: 'case_00001',
    patient_id: 'patient-a',
    group: 'G',
    raw_phase: 'ven',
    canonical_phase: 'NP',
    phase_status: 'normalized',
    scan_idx: '0',
    side: 'R',
    scope_availability: { complete: true, voi: true },
    nifti_path: { raw: 'nifti/a.nii.gz', resolved: '/data/nifti/a.nii.gz', status: 'exists' },
    seg_path: { raw: 'seg/a.nii.gz', resolved: '/data/seg/a.nii.gz', status: 'exists' },
    voi_image_path: { raw: 'voi/a_R.npy', resolved: '/data/voi/a_R.npy', status: 'exists' },
    voi_mask_path: { raw: 'voi/a_R.npy', resolved: '/data/voi/a_R.npy', status: 'exists' },
    has_seg: true,
    has_voi_image: true,
    has_voi_mask: true,
    qc_warnings: [],
    latest_curation_status: null,
  },
  {
    row_id: 'row-b',
    source_row_id: null,
    case_id: 'case_00001',
    patient_id: 'patient-a',
    group: 'G',
    raw_phase: 'ven',
    canonical_phase: 'NP',
    phase_status: 'normalized',
    scan_idx: '1',
    side: 'R',
    scope_availability: { complete: true, voi: true },
    nifti_path: { raw: 'nifti/b.nii.gz', resolved: '/data/nifti/b.nii.gz', status: 'exists' },
    seg_path: { raw: 'seg/b.nii.gz', resolved: '/data/seg/b.nii.gz', status: 'missing' },
    voi_image_path: { raw: 'voi/b_R.npy', resolved: '/data/voi/b_R.npy', status: 'missing' },
    voi_mask_path: { raw: 'voi/b_R.npy', resolved: '/data/voi/b_R.npy', status: 'missing' },
    has_seg: true,
    has_voi_image: true,
    has_voi_mask: true,
    qc_warnings: [
      {
        code: 'missing_seg',
        message: 'SEG is expected but missing or unreadable.',
        severity: 'warning',
        row_id: 'row-b',
        scope: 'complete',
        path_field: 'seg_path',
      },
      {
        code: 'missing_voi_image',
        message: 'VOI image is expected but missing or unreadable.',
        severity: 'warning',
        row_id: 'row-b',
        scope: 'voi',
        path_field: 'voi_image_path',
      },
    ],
    latest_curation_status: null,
  },
]

const history: CurationDecision[] = [
  {
    review_id: 'review-a',
    dataset_id: 'DatasetTest',
    case_id: 'case_00001',
    row_id: 'row-a',
    scope: 'complete',
    target: 'SEG',
    status: 'accepted',
    priority: 'medium',
    comment: 'Looks acceptable.',
    reviewer: 'Dr Curator',
    patient_id: 'patient-a',
    source_row_id: null,
    scan_idx: '0',
    raw_phase: 'ven',
    canonical_phase: 'NP',
    proposed_phase: null,
    side: 'L',
    reviewed_at: '2026-05-27T00:00:00Z',
    nifti_path: null,
    seg_path: null,
    voi_image_path: null,
    voi_mask_path: null,
  },
]

const correctionQueue = {
  dataset_id: 'DatasetTest',
  items: [
    {
      ...history[0],
      review_id: 'queue-a',
      status: 'needs_major_correction',
      priority: 'high',
      comment: 'Needs external correction.',
    },
  ],
}

describe('Main Review Screen UX', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.listCases.mockResolvedValue(cases as never)
    mockedApi.listCaseInventory.mockResolvedValue(inventory as never)
    mockedApi.getCurationHistory.mockResolvedValue(history as never)
    mockedApi.listCorrectionQueue.mockResolvedValue(correctionQueue as never)
    mockedApi.getCaseDossier.mockResolvedValue({
      case_id: 'case_00001',
      core: { case_id: 'case_00001' },
      acquisition: {},
      segmentation_voi: {},
      preprocessing_qc: {},
      external_research: {},
      advanced_raw_fields: [{ row_id: 'row-a', raw: { case_id: 'case_00001' } }],
    })
    mockedApi.loadCaseSource.mockResolvedValue({
      series_id: 'complete:row-a',
      load_handle: 'handle-a',
      shape: [8, 8, 8],
      spacing: [1, 1, 1],
      has_mask: true,
      labels: [1, 2, 3],
    })
    mockedApi.saveCurationDecision.mockResolvedValue({
      ...history[0],
      comment: '',
      reviewer: '',
    })
  })

  it.each([
    [1280, 720],
    [1440, 1000],
    [2560, 1440],
  ])('keeps the cockpit surfaces mounted at %ix%i', async (width, height) => {
    setViewport(width, height)
    renderReviewScreen()

    expect(await screen.findByTestId('main-review-screen')).toBeInTheDocument()
    expect(screen.getByTestId('left-review-panel')).toBeInTheDocument()
    expect(screen.getByTestId('case-navigator')).toBeInTheDocument()
    expect(screen.getByTestId('module-selector')).toBeInTheDocument()
    expect(screen.getByTestId('viewer-grid-2x2')).toBeInTheDocument()
    // bottom drawer is not rendered by default in v2.0 layout
    expect(screen.queryByTestId('bottom-drawer')).not.toBeInTheDocument()
    expect(screen.queryByTestId('scan-idx-selector')).not.toBeInTheDocument()
  })

  it('uses discoverable pane expand controls without changing the default pane order', async () => {
    const user = userEvent.setup()
    const { container } = renderReviewScreen()

    expect(await screen.findByTestId('viewer-grid-2x2')).toBeInTheDocument()
    expect(getPanelOrder(container)).toEqual(['AXI', 'COR', 'SAG', '3D'])

    const expandButtons = await screen.findAllByRole('button', { name: /expand view/i })
    expect(expandButtons).toHaveLength(4)
    expect(expandButtons[0]).toHaveTextContent('Expand')

    await user.click(expandButtons[0])
    expect(await screen.findByRole('button', { name: /reset layout/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /restore view/i })).toHaveTextContent('Restore')
  })

  it('keeps case navigation persistent across left-panel modules', async () => {
    const user = userEvent.setup()
    renderReviewScreen()

    expect(await screen.findByTestId('case-navigator')).toHaveTextContent('1/2')

    for (const moduleName of ['Sources', 'QC', 'Warnings', 'History']) {
      await switchToModule(moduleName)
      expect(screen.getByTestId('case-navigator')).toBeInTheDocument()
    }

    const saveCalls = mockedApi.saveCurationDecision.mock.calls.length
    await user.click(within(screen.getByTestId('case-navigator')).getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(screen.getByTestId('case-navigator')).toHaveTextContent('2/2'))
    expect(mockedApi.saveCurationDecision).toHaveBeenCalledTimes(saveCalls)
  })

  it('loads scan 0 complete CT by default', async () => {
    renderReviewScreen()

    await waitFor(() =>
      expect(mockedApi.loadCaseSource).toHaveBeenCalledWith(
        'DatasetTest',
        'case_00001',
        'row-a',
        'complete',
        expect.any(Object),
      ),
    )
    // source-navigator lives in the Sources module
    await switchToModule('Sources')
    const sourceNavigator = screen.getByTestId('source-navigator')
    expect(sourceNavigator).toHaveTextContent('Scan 0')
    expect(sourceNavigator).toHaveTextContent('NP · scan 0 · Complete CT')
  })

  it('shows a compact source matrix with visible source states and no primary table', async () => {
    renderReviewScreen()
    await switchToModule('Sources')
    const sourceNavigator = await screen.findByTestId('source-navigator')

    const phaseChips = within(sourceNavigator).getAllByTestId('phase-filter-chip')
    expect(phaseChips.map((chip) => chip.textContent)).toEqual(['NP', 'CMP', 'NC', 'EXC'])
    expect(phaseChips.find((chip) => chip.textContent === 'CMP')).toBeDisabled()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByTestId('inventory-detail')).toHaveTextContent('Inventory detail')

    expect(
      within(sourceNavigator).getByRole('button', { name: /NP · scan 0 · Complete CT/i }),
    ).toHaveAttribute('data-source-state', 'selected')
    expect(
      within(sourceNavigator).getByRole('button', { name: /NP · scan 0 · VOI L/i }),
    ).toHaveAttribute('data-source-state', 'available')
    expect(
      within(sourceNavigator).getByRole('button', { name: /NP · scan 1 · Complete CT/i }),
    ).toHaveAttribute('data-source-state', 'warning')
    const missingVoi = within(sourceNavigator).getByRole('button', { name: /NP · scan 1 · VOI R/i })
    expect(missingVoi).toBeDisabled()
    expect(missingVoi).toHaveAttribute('data-source-state', 'missing')
  })

  it('toggles CT to VOI with one source-card click inside the Main Review Screen', async () => {
    const user = userEvent.setup()
    renderReviewScreen()
    // source-navigator lives in the Sources module
    await switchToModule('Sources')
    const sourceNavigator = await screen.findByTestId('source-navigator')

    await user.click(within(sourceNavigator).getByRole('button', { name: /NP · scan 0 · VOI L/i }))

    await waitFor(() =>
      expect(mockedApi.loadCaseSource).toHaveBeenLastCalledWith(
        'DatasetTest',
        'case_00001',
        'row-a',
        'voi',
        expect.any(Object),
      ),
    )
    expect(screen.getByTestId('main-review-screen')).toBeInTheDocument()
  })

  it('keeps MPR pane order fixed and applies isotropic VOI fit metadata', async () => {
    mockedApi.loadCaseSource.mockImplementation(async (_datasetId, _caseId, _rowId, nextScope) => ({
      series_id: `${nextScope}:row-a`,
      load_handle: `handle-${nextScope}`,
      shape: nextScope === 'voi' ? [32, 28, 12] : [256, 256, 40],
      spacing: nextScope === 'voi' ? [0.8, 0.9, 4] : [0.7, 0.7, 5],
      has_mask: true,
      labels: [1, 2, 3],
    }))

    const user = userEvent.setup()
    const { container } = renderReviewScreen()

    await screen.findByTestId('viewer-grid-2x2')
    expect(getPanelOrder(container)).toEqual(['AXI', 'COR', 'SAG', '3D'])

    await waitFor(() =>
      expect(
        screen
          .getAllByTestId('slice-view')
          .every((node) => node.getAttribute('data-spacing') === '0.7,0.7,5'),
      ).toBe(true),
    )

    await switchToModule('Sources')
    const sourceNavigator = await screen.findByTestId('source-navigator')
    await user.click(within(sourceNavigator).getByRole('button', { name: /NP · scan 0 · VOI L/i }))

    await waitFor(() =>
      expect(mockedApi.loadCaseSource).toHaveBeenLastCalledWith(
        'DatasetTest',
        'case_00001',
        'row-a',
        'voi',
        expect.any(Object),
      ),
    )
    expect(getPanelOrder(container)).toEqual(['AXI', 'COR', 'SAG', '3D'])
    await waitFor(() => {
      const slices = screen.getAllByTestId('slice-view')
      expect(slices).toHaveLength(3)
      expect(slices.every((node) => node.getAttribute('data-fit-label') === 'VOI fit')).toBe(true)
      expect(slices.every((node) => node.getAttribute('data-spacing') === '1,1,1')).toBe(true)
    })
  })

  it('supports filled and contour overlay modes with a viewer HUD and popover', async () => {
    const user = userEvent.setup()
    renderReviewScreen()
    const viewerRegion = await screen.findByTestId('mpr-viewer-region')
    const overlayLegend = await within(viewerRegion).findByTestId('overlay-legend')
    const overlayHud = within(viewerRegion).getByTestId('overlay-status-hud')
    const overlayButton = within(viewerRegion).getByTestId('overlay-controls-button')

    expect(overlayLegend).toContainElement(overlayButton)
    expect(overlayLegend).toHaveAttribute('data-overlay-placement', 'top-center')
    expect(overlayHud).toHaveTextContent('Overlay Filled')
    expect(overlayHud).toHaveTextContent('Kidney')
    expect(overlayHud).toHaveTextContent('Tumor')
    expect(overlayButton).toHaveTextContent('Overlay')

    await user.click(overlayButton)
    await user.click(await screen.findByTestId('overlay-mode-contour'))
    expect(overlayHud).toHaveTextContent('Overlay Contour')
    await user.click(screen.getByTestId('overlay-mode-filled'))
    expect(overlayHud).toHaveTextContent('Overlay Filled')
  })

  it('saves accepted case QC through Save & Next', async () => {
    const user = userEvent.setup()
    renderReviewScreen()
    // QC panel lives in the QC module
    await switchToModule('QC')
    await screen.findByTestId('right-qc-panel')
    const saveAndNext = screen.getByTestId('save-and-next')
    await waitFor(() => expect(saveAndNext).toBeEnabled())

    await user.click(saveAndNext)

    await waitFor(() =>
      expect(mockedApi.saveCurationDecision).toHaveBeenCalledWith(
        'DatasetTest',
        expect.objectContaining({
          case_id: 'case_00001',
          row_id: 'row-a',
          scope: 'complete',
          target: 'SEG',
          status: 'accepted',
          add_to_queue: false,
        }),
      ),
    )
  })

  it('automatically queues Needs correction', async () => {
    const user = userEvent.setup()
    renderReviewScreen()
    // QC panel lives in the QC module
    await switchToModule('QC')
    const qcPanel = await screen.findByTestId('right-qc-panel')

    await user.click(within(qcPanel).getByRole('button', { name: 'Needs correction' }))
    await user.click(screen.getByTestId('save-and-next'))

    await waitFor(() =>
      expect(mockedApi.saveCurationDecision).toHaveBeenCalledWith(
        'DatasetTest',
        expect.objectContaining({
          status: 'needs_major_correction',
          add_to_queue: true,
          priority: 'high',
        }),
      ),
    )
  })

  it('blocks QC when Missing SEG is active and keeps Missing VOI informational', async () => {
    const user = userEvent.setup()
    renderReviewScreen()
    // select a source with missing SEG via the Sources module
    await switchToModule('Sources')
    const sourceNavigator = await screen.findByTestId('source-navigator')

    await user.click(within(sourceNavigator).getByRole('button', { name: /NP · scan 1 · Complete CT/i }))

    // QC block message and Save & Next state are in the QC module
    await switchToModule('QC')
    expect(await screen.findByText('Missing SEG blocks case QC.')).toBeInTheDocument()
    expect(screen.getByTestId('save-and-next')).toBeDisabled()
    // Missing VOI is informational — visible in the Warnings module
    await switchToModule('Warnings')
    expect(await screen.findByText('Missing VOI')).toBeInTheDocument()
  })

  it('opens Case Data as a searchable modal with raw fields and paths hidden', async () => {
    const user = userEvent.setup()
    renderReviewScreen()
    // case-data-action button lives in the Case Data module
    await switchToModule('Case Data')
    await screen.findByTestId('case-data-action')

    await user.click(screen.getByTestId('case-data-action'))

    const modal = await screen.findByTestId('case-data-modal')
    expect(within(modal).getByText('Case Summary')).toBeInTheDocument()
    expect(within(modal).getByText('Imaging Availability')).toBeInTheDocument()
    expect(within(modal).getByText('Segmentation & VOI')).toBeInTheDocument()
    expect(within(modal).getByText('QC History')).toBeInTheDocument()
    expect(within(modal).getByLabelText('Search metadata')).toBeInTheDocument()
    expect(within(modal).getByTestId('raw-fields')).toHaveTextContent('Raw fields hidden by default')
    expect(within(modal).getByTestId('technical-paths')).toHaveTextContent('Technical paths hidden by default')
  })

  it('shows shortcut help without leaving the Main Review Screen', async () => {
    const user = userEvent.setup()
    renderReviewScreen()
    await user.click(await screen.findByRole('button', { name: /keyboard shortcuts/i }))

    expect(screen.getByTestId('help-overlay')).toHaveTextContent('Review shortcuts')
    expect(screen.getByTestId('main-review-screen')).toBeInTheDocument()
  })

  it('shows phase correction dialog scoped to the current scan', async () => {
    const user = userEvent.setup()
    renderReviewScreen()
    // Phase correction button lives in the Case Data module
    await switchToModule('Case Data')

    await user.click(await screen.findByRole('button', { name: 'Phase correction' }))

    expect(screen.getByText('Controlled phase correction')).toBeInTheDocument()
    expect(screen.getByText(/no files are moved/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /confirm phase correction/i })).toBeInTheDocument()
  })
})

async function switchToModule(moduleName: string) {
  const user = userEvent.setup()
  await user.click(screen.getByRole('combobox', { name: 'Module' }))
  const option = await screen.findByRole('option', { name: new RegExp(moduleName, 'i') })
  await user.click(option)
}

function renderReviewScreen() {
  return render(
    <MemoryRouter initialEntries={['/datasets/DatasetTest/review/case_00001']}>
      <Routes>
        <Route path="/datasets/:dsid/review/:caseId" element={<MainReviewScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

function setViewport(width: number, height: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: height })
  fireEvent(window, new Event('resize'))
}

function getPanelOrder(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('[data-panel]')).map(
    (node) => node.getAttribute('data-panel') ?? '',
  )
}
