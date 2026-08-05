import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from '../services/router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CaseReviewPage from './CaseReviewPage'
import CaseWorklistPage from './CaseWorklistPage'
import { apiClient } from '../services/api'

vi.mock('../components/viewer/SliceView', () => ({
  default: () => <div data-testid="slice-view">Slice</div>,
}))

vi.mock('../components/viewer/Surface3DView', () => ({
  default: () => <div data-testid="surface-view">Surface</div>,
}))

vi.mock('../services/api', async () => {
  const apiClient = {
    getHealth: vi.fn(),
    getDatabaseValidation: vi.fn(),
    listCases: vi.fn(),
    listCaseInventory: vi.fn(),
    getCaseDossier: vi.fn(),
    getCurationHistory: vi.fn(),
    listCorrectionQueue: vi.fn(),
    loadCaseSource: vi.fn(),
    saveCurationDecision: vi.fn(),
    applyReviewOperations: vi.fn(),
    previewMetadataSync: vi.fn(),
    applyMetadataSync: vi.fn(),
  }
  return {
    apiClient,
    getApiErrorMessage: (error: unknown) =>
      error instanceof Error ? error.message : 'Unexpected API error',
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
]

const inventory = [
  {
    row_index: 0,
    row_id: 'row-a',
    source_row_id: null,
    series_id: 'nifti:a',
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
    deleted: false,
    qc_warnings: [],
    latest_curation_status: null,
  },
  {
    row_index: 1,
    row_id: 'row-a-r',
    source_row_id: null,
    series_id: 'nifti:a',
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
    deleted: false,
    qc_warnings: [],
    latest_curation_status: null,
  },
  {
    row_index: 2,
    row_id: 'row-b',
    source_row_id: null,
    series_id: 'nifti:b',
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
    deleted: false,
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

const validationReport = {
  dataset_id: 'DatasetTest',
  has_database: true,
  row_count: 3,
  case_count: 1,
  required_columns: [
    { name: 'case_id', present: true, alternatives: [] },
    { name: 'nifti_path', present: true, alternatives: [] },
  ],
  warnings: [
    {
      code: 'missing_voi_image',
      message: 'VOI image is expected but missing or unreadable.',
      severity: 'warning',
      row_id: 'row-b',
      scope: 'voi',
      path_field: 'voi_image_path',
    },
  ],
}

const history = [
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

describe('v2 medical curation UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.getHealth.mockResolvedValue({
      status: 'ok',
      allow_data_mutations: false,
      mpr_renderer: 'png',
      webui_state_dir: '',
    } as never)
    mockedApi.getDatabaseValidation.mockResolvedValue(validationReport as never)
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
      labels: [1, 2],
    })
    mockedApi.saveCurationDecision.mockResolvedValue({
      review_id: 'review-a',
      dataset_id: 'DatasetTest',
      case_id: 'case_00001',
      row_id: 'row-a',
      scope: 'complete',
      target: 'SEG',
      status: 'accepted',
      priority: 'medium',
      comment: '',
      reviewer: '',
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
    })
    mockedApi.applyReviewOperations.mockResolvedValue({
      batch_id: 'batch-a',
      applied_at: '2026-05-27T00:00:00Z',
      summary: {
        requested: 1,
        applied: 1,
        skipped: 0,
        failed: 0,
      },
      results: [
        {
          patient_id: 'case_00001',
          series_id: 'nifti:a',
          action: 'reclassify',
          target_phase: 'CMP',
          status: 'applied',
          message: 'phase.json updated',
          moved_files: [],
          metadata_updated: true,
        },
      ],
    })
    mockedApi.previewMetadataSync.mockResolvedValue({
      dataset_id: 'DatasetTest',
      summary: {
        phase_changes: 0,
        delete_changes: 0,
        restore_changes: 0,
        already_consolidated: 2,
        conflicts: 0,
        noop: 0,
        voi_catalog_changes: 0,
        total_rows: 2,
      },
      changes: [],
    })
    mockedApi.applyMetadataSync.mockResolvedValue({
      dataset_id: 'DatasetTest',
      batch_id: 'metadata-batch-a',
      applied_at: '2026-05-27T00:00:00Z',
      metadata_updated: true,
      summary: {
        phase_changes: 1,
        delete_changes: 1,
        restore_changes: 1,
        already_consolidated: 0,
        conflicts: 0,
        noop: 0,
        voi_catalog_changes: 1,
        total_rows: 3,
      },
      changes: [],
    })
  })

  it('renders one worklist row per case with core curation columns', async () => {
    render(
      <MemoryRouter initialEntries={['/datasets/DatasetTest/cases']}>
        <Routes>
          <Route path="/datasets/:dsid/cases" element={<CaseWorklistPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await screen.findByText('Ready for review')
    const validationBanner = screen.getByTestId('dataset-validation-banner')
    expect(validationBanner).toHaveTextContent('Ready for review')
    expect(validationBanner).toHaveTextContent('database.csv: Present')
    expect(validationBanner).toHaveTextContent('Rows: 3')
    expect(validationBanner).toHaveTextContent('Cases: 1')
    expect(validationBanner).toHaveTextContent('Required columns: 2/2')
    expect(validationBanner).toHaveTextContent('Warnings: 1')

    const rows = await screen.findAllByTestId('case-worklist-row')
    expect(rows).toHaveLength(1)
    expect(within(rows[0]).getByText('case_00001')).toBeInTheDocument()
    expect(within(rows[0]).getByText('G')).toBeInTheDocument()
    expect(within(rows[0]).getByText('NP')).toBeInTheDocument()
    expect(within(rows[0]).getByText('CMP')).toBeInTheDocument()
    expect(within(rows[0]).getAllByText('2').length).toBeGreaterThan(0)
    expect(within(rows[0]).getByText('L / R')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Not reviewed')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Yes')).toBeInTheDocument()
  })

  it('opens correction queue and exposes CSV export', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/datasets/DatasetTest/cases']}>
        <Routes>
          <Route path="/datasets/:dsid/cases" element={<CaseWorklistPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await screen.findAllByTestId('case-worklist-row')
    await user.click(screen.getByRole('button', { name: /correction queue/i }))

    expect(await screen.findByRole('heading', { name: 'Correction Queue' })).toBeInTheDocument()
    expect(screen.getByText('Needs external correction.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /export csv/i })).toHaveAttribute(
      'href',
      '/api/datasets/DatasetTest/curation/correction-queue.csv',
    )
  })

  it('opens case review with top phase controls and no curation panels', async () => {
    renderReviewPage()

    expect(await screen.findByText('case_00001')).toBeInTheDocument()
    const phaseButtons = await screen.findAllByTestId('phase-button')
    expect(phaseButtons.map((button) => button.textContent)).toEqual(['NC', 'CMP', 'NP', 'DELAY'])
    expect(await screen.findByTestId('scan-idx-selector')).toBeInTheDocument()
    expect(await screen.findByTestId('side-selector')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'NP' })).toHaveClass('MuiButton-contained')
    expect(screen.queryByText('QC Warnings')).not.toBeInTheDocument()
    expect(screen.queryByText('Segmentation QC')).not.toBeInTheDocument()
    expect(screen.queryByTestId('curation-history-panel')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /advanced metadata/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeInTheDocument()
    expect(screen.queryByText(/current:/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reclassify/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^undo$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /apply changes/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Soft Tissue' })).toHaveClass('MuiButton-contained')
    expect(screen.getByRole('button', { name: 'Kidney' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pancreas' })).toBeInTheDocument()
    expect(screen.getByText('WW 400')).toBeInTheDocument()
    expect(screen.getByText('WL 50')).toBeInTheDocument()
  })

  it('applies selected phase correction through top phase buttons', async () => {
    const user = userEvent.setup()
    renderReviewPage()
    await screen.findAllByTestId('phase-button')
    await waitFor(() => expect(screen.getByRole('button', { name: 'CMP' })).not.toBeDisabled())
    await user.click(screen.getByRole('button', { name: 'CMP' }))

    await waitFor(() =>
      expect(mockedApi.applyReviewOperations).toHaveBeenCalledWith('DatasetTest', {
        operations: [
          {
            patient_id: 'case_00001',
            series_id: 'nifti:a',
            action: 'reclassify',
            target_phase: 'CMP',
          },
        ],
      }),
    )
  })

  it('disables phase correction when reviewing VOI scope', async () => {
    const user = userEvent.setup()
    renderReviewPage()
    await screen.findAllByTestId('phase-button')

    await user.click(screen.getByRole('button', { name: 'VOI' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'CMP' })).toBeDisabled())
    expect(mockedApi.applyReviewOperations).not.toHaveBeenCalled()
  })

  it('calculates window level from a custom HU range', async () => {
    const user = userEvent.setup()
    renderReviewPage()
    await screen.findAllByTestId('phase-button')

    await user.click(screen.getByRole('button', { name: 'Custom' }))
    const minInput = screen.getByRole('spinbutton', { name: 'Min HU' })
    const maxInput = screen.getByRole('spinbutton', { name: 'Max HU' })
    await user.clear(minInput)
    await user.type(minInput, '-100')
    await user.clear(maxInput)
    await user.type(maxInput, '200')

    await waitFor(() => expect(screen.getByText('WW 300')).toBeInTheDocument())
    expect(screen.getByText('WL 50')).toBeInTheDocument()
  })

  it('moves selected scan to recycle bin through delete button', async () => {
    const user = userEvent.setup()
    renderReviewPage()
    await screen.findAllByTestId('phase-button')
    await waitFor(() => expect(screen.getByRole('button', { name: /^delete$/i })).not.toBeDisabled())

    await user.click(screen.getByRole('button', { name: /^delete$/i }))

    await waitFor(() =>
      expect(mockedApi.applyReviewOperations).toHaveBeenCalledWith('DatasetTest', {
        operations: [
          {
            patient_id: 'case_00001',
            series_id: 'nifti:a',
            action: 'delete',
          },
        ],
      }),
    )
  })

  it('previews and confirms metadata sync updates', async () => {
    const user = userEvent.setup()
    mockedApi.previewMetadataSync.mockResolvedValue({
      dataset_id: 'DatasetTest',
      summary: {
        phase_changes: 1,
        delete_changes: 1,
        restore_changes: 1,
        already_consolidated: 3,
        conflicts: 0,
        noop: 0,
        voi_catalog_changes: 1,
        total_rows: 6,
      },
      changes: [
        {
          kind: 'phase_changes',
          target: 'metadata',
          filename: 'a.nii.gz',
          case_id: 'case_00001',
          scan_idx: '0',
          side: null,
          row_index: 0,
          message: 'phase.json phase differs from metadata.jsonl.',
          current_phase: 'NP',
          target_phase: 'CMP',
          current_relative_path: null,
          target_relative_path: null,
        },
        {
          kind: 'delete_changes',
          target: 'voi_catalog',
          filename: 'a_L.npy',
          case_id: 'case_00001',
          scan_idx: '0',
          side: 'L',
          row_index: 1,
          message: 'VOI image is in recycle bin.',
          current_phase: null,
          target_phase: null,
          current_relative_path: 'voi/images/G/case_00001/a_L.npy',
          target_relative_path: 'voi/deleted/images/G/case_00001/a_L.npy',
        },
      ],
    } as never)

    renderReviewPage()
    await screen.findAllByTestId('phase-button')
    await user.click(screen.getByRole('button', { name: /update metadata/i }))

    expect(await screen.findByRole('heading', { name: 'Update metadata' })).toBeInTheDocument()
    expect(screen.getByText('Phase 1')).toBeInTheDocument()
    expect(screen.getByText('Delete 1')).toBeInTheDocument()
    expect(screen.getByText('Restore 1')).toBeInTheDocument()
    expect(screen.getByText('VOI 1')).toBeInTheDocument()
    expect(screen.getByText('NP -> CMP')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /apply update/i }))

    await waitFor(() => expect(mockedApi.applyMetadataSync).toHaveBeenCalledWith('DatasetTest'))
    await waitFor(() => expect(mockedApi.listCaseInventory).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/metadata.jsonl updated/i)).toBeInTheDocument()
  })

  it('blocks metadata sync confirmation when preview has conflicts', async () => {
    const user = userEvent.setup()
    mockedApi.previewMetadataSync.mockResolvedValue({
      dataset_id: 'DatasetTest',
      summary: {
        phase_changes: 0,
        delete_changes: 0,
        restore_changes: 0,
        already_consolidated: 0,
        conflicts: 1,
        noop: 0,
        voi_catalog_changes: 0,
        total_rows: 1,
      },
      changes: [
        {
          kind: 'conflicts',
          target: 'metadata',
          filename: 'a.nii.gz',
          case_id: 'case_00001',
          scan_idx: '0',
          side: null,
          row_index: 0,
          message: 'Both active and deleted NIfTI files exist.',
          current_phase: null,
          target_phase: null,
          current_relative_path: 'nifti/a.nii.gz',
          target_relative_path: null,
        },
      ],
    } as never)

    renderReviewPage()
    await screen.findAllByTestId('phase-button')
    await user.click(screen.getByRole('button', { name: /update metadata/i }))

    expect(await screen.findByText(/resolve conflicts/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /apply update/i })).toBeDisabled()
    expect(mockedApi.applyMetadataSync).not.toHaveBeenCalled()
  })

  it('restores selected deleted scan through restore button', async () => {
    const user = userEvent.setup()
    mockedApi.listCaseInventory.mockResolvedValue([
      {
        ...inventory[0],
        deleted: true,
        nifti_path: {
          raw: 'deleted/nifti/a.nii.gz',
          resolved: '/data/deleted/nifti/a.nii.gz',
          status: 'exists',
        },
      },
    ] as never)

    renderReviewPage()
    await waitFor(() => expect(screen.getByRole('button', { name: /^restore$/i })).not.toBeDisabled())

    await user.click(screen.getByRole('button', { name: /^restore$/i }))

    await waitFor(() =>
      expect(mockedApi.applyReviewOperations).toHaveBeenCalledWith('DatasetTest', {
        operations: [
          {
            patient_id: 'case_00001',
            series_id: 'nifti:a',
            action: 'restore',
          },
        ],
      }),
    )
  })
})

function renderReviewPage() {
  render(
    <MemoryRouter initialEntries={['/datasets/DatasetTest/cases/case_00001/review']}>
      <Routes>
        <Route path="/datasets/:dsid/cases/:caseId/review" element={<CaseReviewPage />} />
      </Routes>
    </MemoryRouter>,
  )
}
