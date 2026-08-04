import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DatasetSelectorPage from './DatasetSelectorPage'
import { apiClient, type WorkspaceInspection, type WorkspaceStatus } from '../services/api'
import { MemoryRouter, Route, Routes } from '../services/router'

const mockedSettings = vi.hoisted(() => ({
  allSettings: {} as Record<string, { last_patient?: string }>,
}))

vi.mock('../hooks/useSettings', () => ({
  useSettings: () => ({
    allSettings: mockedSettings.allSettings,
    error: null,
    loading: false,
  }),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      clearWorkspace: vi.fn(),
      inspectWorkspace: vi.fn(),
      putWorkspace: vi.fn(),
    },
  }
})

const mockedApi = vi.mocked(apiClient)

const emptyWorkspace: WorkspaceStatus = {
  configured: false,
  dataset_id: null,
  dataset_key: null,
  dataset_kind: null,
  dataset_path: null,
  workspace_dir: null,
  recent_datasets: [],
}

const canonicalInspection: WorkspaceInspection = {
  valid: true,
  dataset_path: '/data/Dataset420',
  dataset_id: 'Dataset420',
  dataset_key: 'abc123def456',
  dataset_kind: 'canonical',
  markers: {
    database_csv: true,
    metadata_jsonl: false,
    manifest_csv: false,
    nifti: true,
    seg: true,
    voi: false,
  },
  summary: {
    case_count: 186,
    volume_count: 604,
    nifti_count: 604,
    voi_image_count: 0,
    segmentation_count: 186,
    voi_mask_count: 0,
    warning_count: 0,
    warnings_truncated: false,
  },
  state: {
    path: '/data/Dataset420/.webui',
    exists: false,
    writable: true,
  },
  warnings: [],
}

describe('DatasetSelectorPage', () => {
  beforeEach(() => {
    delete window.__TAURI__
    vi.clearAllMocks()
    mockedSettings.allSettings = {}
    mockedApi.putWorkspace.mockResolvedValue({
      ...emptyWorkspace,
      configured: true,
      dataset_id: 'Dataset420',
      dataset_key: 'abc123def456',
      dataset_kind: 'canonical',
      dataset_path: '/data/Dataset420',
      workspace_dir: '/data/Dataset420/.webui',
    })
  })

  afterEach(() => {
    delete window.__TAURI__
  })

  it('shows Browse only in desktop and does not inspect after selection', async () => {
    const user = userEvent.setup()
    const invoke = vi.fn().mockResolvedValue('C:\\Research\\Dataset420')
    window.__TAURI__ = { core: { invoke } }
    renderPage(emptyWorkspace)

    await user.click(screen.getByRole('button', { name: /Browse/i }))

    expect(invoke).toHaveBeenCalledWith('browse_for_dataset_directory')
    expect(screen.getByLabelText('Dataset path visible to the server')).toHaveValue(
      'C:\\Research\\Dataset420',
    )
    expect(mockedApi.inspectWorkspace).not.toHaveBeenCalled()
  })

  it('does not show Browse in the web runtime', () => {
    renderPage(emptyWorkspace)

    expect(screen.queryByRole('button', { name: /Browse/i })).not.toBeInTheDocument()
  })

  it('keeps the current path when the desktop folder dialog is cancelled', async () => {
    const user = userEvent.setup()
    const invoke = vi.fn().mockResolvedValue(null)
    window.__TAURI__ = { core: { invoke } }
    renderPage(emptyWorkspace)
    const input = screen.getByLabelText('Dataset path visible to the server')
    await user.type(input, 'C:\\Research\\Current')

    await user.click(screen.getByRole('button', { name: /Browse/i }))

    expect(input).toHaveValue('C:\\Research\\Current')
    expect(mockedApi.inspectWorkspace).not.toHaveBeenCalled()
  })

  it('shows the loading and workspace error states', () => {
    const { rerender } = render(
      <MemoryRouter>
        <DatasetSelectorPage
          workspace={emptyWorkspace}
          workspaceLoading
          workspaceError={null}
          onWorkspaceChange={vi.fn()}
        />
      </MemoryRouter>,
    )

    expect(screen.getByRole('progressbar')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Inspect' })).toBeDisabled()

    rerender(
      <MemoryRouter>
        <DatasetSelectorPage
          workspace={emptyWorkspace}
          workspaceLoading={false}
          workspaceError="Workspace could not be loaded"
          onWorkspaceChange={vi.fn()}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Workspace could not be loaded')).toBeInTheDocument()
  })

  it('inspects before activation and opens canonical datasets in Cases', async () => {
    const user = userEvent.setup()
    mockedApi.inspectWorkspace.mockResolvedValue(canonicalInspection)
    renderPage(emptyWorkspace)

    await user.type(screen.getByLabelText('Dataset path visible to the server'), '/data/Dataset420')
    await user.click(screen.getByRole('button', { name: 'Inspect' }))

    expect(await screen.findByText('604')).toBeInTheDocument()
    expect(mockedApi.putWorkspace).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Open dataset' }))

    await waitFor(() => expect(mockedApi.putWorkspace).toHaveBeenCalledWith('/data/Dataset420'))
    expect(await screen.findByText('Cases destination')).toBeInTheDocument()
  })

  it('keeps incomplete datasets as read-only diagnosis', async () => {
    const user = userEvent.setup()
    mockedApi.inspectWorkspace.mockResolvedValue({
      ...canonicalInspection,
      valid: false,
      dataset_kind: 'incomplete',
      summary: { ...canonicalInspection.summary, volume_count: 0, warning_count: 1 },
      warnings: [
        {
          code: 'no_visualizable_volume',
          message: 'No readable volume was found.',
          severity: 'error',
        },
      ],
    })
    renderPage(emptyWorkspace)

    await user.type(screen.getByLabelText('Dataset path visible to the server'), '/data/incomplete')
    await user.click(screen.getByRole('button', { name: 'Inspect' }))

    expect(await screen.findByText('Activation blocked')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open dataset' })).not.toBeInTheDocument()
    expect(mockedApi.putWorkspace).not.toHaveBeenCalled()
  })

  it('routes legacy datasets to Patients and invalidates stale previews on edit', async () => {
    const user = userEvent.setup()
    mockedApi.inspectWorkspace.mockResolvedValue({
      ...canonicalInspection,
      dataset_kind: 'legacy',
    })
    mockedApi.putWorkspace.mockResolvedValue({
      ...emptyWorkspace,
      configured: true,
      dataset_id: 'Dataset420',
      dataset_key: 'abc123def456',
      dataset_kind: 'legacy',
      dataset_path: '/data/Dataset420',
      workspace_dir: '/data/Dataset420/.webui',
    })
    renderPage(emptyWorkspace)

    const input = screen.getByLabelText('Dataset path visible to the server')
    await user.type(input, '/data/legacy')
    await user.click(screen.getByRole('button', { name: 'Inspect' }))
    expect(await screen.findByRole('button', { name: 'Open dataset' })).toBeInTheDocument()

    await user.type(input, '-changed')
    expect(screen.queryByRole('button', { name: 'Open dataset' })).not.toBeInTheDocument()

    await user.clear(input)
    await user.type(input, '/data/legacy')
    await user.click(screen.getByRole('button', { name: 'Inspect' }))
    await user.click(await screen.findByRole('button', { name: 'Open dataset' }))

    expect(await screen.findByText('Patients destination')).toBeInTheDocument()
  })

  it.each([
    ['nifti_collection', '/data/nifti'],
    ['voi_collection', '/data/voi'],
  ] as const)('routes %s datasets to Patients', async (datasetKind, datasetPath) => {
    const user = userEvent.setup()
    mockedApi.inspectWorkspace.mockResolvedValue({
      ...canonicalInspection,
      dataset_kind: datasetKind,
      dataset_path: datasetPath,
    })
    mockedApi.putWorkspace.mockResolvedValue({
      ...emptyWorkspace,
      configured: true,
      dataset_id: 'Dataset420',
      dataset_key: 'abc123def456',
      dataset_kind: datasetKind,
      dataset_path: datasetPath,
      workspace_dir: `${datasetPath}/.webui`,
    })
    renderPage(emptyWorkspace)

    await user.type(screen.getByLabelText('Dataset path visible to the server'), datasetPath)
    await user.click(screen.getByRole('button', { name: 'Inspect' }))
    await user.click(await screen.findByRole('button', { name: 'Open dataset' }))

    expect(await screen.findByText('Patients destination')).toBeInTheDocument()
  })

  it('offers removal when a recent dataset is unavailable', async () => {
    const user = userEvent.setup()
    const workspace = {
      ...emptyWorkspace,
      recent_datasets: [
        {
          dataset_path: '/data/missing',
          display_name: 'missing',
          dataset_key: 'missing-key',
          dataset_kind: 'legacy' as const,
          last_opened_at: '2026-08-03T12:00:00+00:00',
        },
      ],
    }
    mockedApi.inspectWorkspace.mockRejectedValue(new Error('Dataset path does not exist'))
    mockedApi.clearWorkspace.mockResolvedValue(emptyWorkspace)
    renderPage(workspace)

    await user.click(screen.getByRole('button', { name: /missing.*\/data\/missing/i }))
    expect(mockedApi.inspectWorkspace).toHaveBeenCalledWith('/data/missing')
    expect(mockedApi.putWorkspace).not.toHaveBeenCalled()
    expect(await screen.findByText('Dataset path does not exist')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove from recent' }))

    await waitFor(() => expect(mockedApi.clearWorkspace).toHaveBeenCalledWith('missing-key'))
  })

  it('re-inspects and directly opens the last converter dataset in Cases', async () => {
    const user = userEvent.setup()
    const activeWorkspace: WorkspaceStatus = {
      ...emptyWorkspace,
      configured: true,
      dataset_id: 'Dataset420',
      dataset_key: 'abc123def456',
      dataset_kind: 'converter_output',
      dataset_path: '/data/Dataset420',
      workspace_dir: '/data/Dataset420/.webui',
    }
    mockedApi.inspectWorkspace.mockResolvedValue({
      ...canonicalInspection,
      dataset_kind: 'converter_output',
    })
    mockedApi.putWorkspace.mockResolvedValue({
      ...activeWorkspace,
      dataset_kind: 'converter_output',
    })
    renderPage(activeWorkspace)

    await user.click(screen.getByRole('button', { name: 'Open last dataset' }))

    await waitFor(() =>
      expect(mockedApi.inspectWorkspace).toHaveBeenCalledWith('/data/Dataset420'),
    )
    expect(await screen.findByText('Cases destination')).toBeInTheDocument()
  })

  it('re-inspects before resuming the active case', async () => {
    const user = userEvent.setup()
    const activeWorkspace: WorkspaceStatus = {
      ...emptyWorkspace,
      configured: true,
      dataset_id: 'Dataset420',
      dataset_key: 'abc123def456',
      dataset_kind: 'canonical',
      dataset_path: '/data/Dataset420',
      workspace_dir: '/data/Dataset420/.webui',
    }
    mockedSettings.allSettings = {
      Dataset420: { last_patient: 'case_00002' },
    }
    mockedApi.inspectWorkspace.mockResolvedValue(canonicalInspection)
    mockedApi.putWorkspace.mockResolvedValue(activeWorkspace)
    renderPage(activeWorkspace)

    await user.click(screen.getByRole('button', { name: 'Resume case_00002' }))

    await waitFor(() =>
      expect(mockedApi.inspectWorkspace).toHaveBeenCalledWith('/data/Dataset420'),
    )
    expect(await screen.findByText('Case review destination')).toBeInTheDocument()
  })
})

function renderPage(workspace: WorkspaceStatus) {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route
          path="/"
          element={
            <DatasetSelectorPage
              workspace={workspace}
              workspaceLoading={false}
              workspaceError={null}
              onWorkspaceChange={vi.fn()}
            />
          }
        />
        <Route path="/datasets/:dsid/cases" element={<div>Cases destination</div>} />
        <Route
          path="/datasets/:dsid/cases/:caseId/review"
          element={<div>Case review destination</div>}
        />
        <Route path="/datasets/:dsid/patients" element={<div>Patients destination</div>} />
      </Routes>
    </MemoryRouter>,
  )
}
