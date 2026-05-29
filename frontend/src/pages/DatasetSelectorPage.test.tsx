import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DatasetSelectorPage from './DatasetSelectorPage'
import { apiClient, type WorkspaceStatus } from '../services/api'

vi.mock('../services/api', async () => {
  const apiClient = {
    clearWorkspace: vi.fn(),
    getDatabaseValidation: vi.fn(),
    getSettings: vi.fn(),
    listCases: vi.fn(),
    listDatasetBrowserPath: vi.fn(),
    listDatasetBrowserRoots: vi.fn(),
    listDatasets: vi.fn(),
    validateWorkspaceSelection: vi.fn(),
  }
  return {
    apiClient,
    getApiErrorMessage: (error: unknown) =>
      error instanceof Error ? error.message : 'Unexpected API error',
  }
})

const mockedApi = vi.mocked(apiClient)

const emptyWorkspace: WorkspaceStatus = {
  configured: false,
  dataset_id: null,
  dataset_path: null,
  database_csv_path: null,
  workspace_dir: null,
}

const activeWorkspace: WorkspaceStatus = {
  configured: true,
  dataset_id: 'DatasetLite',
  dataset_path: '/data/DatasetLite',
  database_csv_path: '/data/DatasetLite/database.csv',
  workspace_dir: '/state/DatasetLite',
}

describe('DatasetSelectorPage setup workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.listDatasetBrowserRoots.mockResolvedValue({
      roots: [
        {
          label: 'Container dataset mount',
          path: '/data',
          source: '/data',
          exists: true,
          readable: true,
        },
      ],
    })
    mockedApi.listDatasetBrowserPath.mockResolvedValue({
      path: '/data',
      parent_path: null,
      entries: [
        {
          name: 'DatasetLite',
          path: '/data/DatasetLite',
          type: 'directory',
          is_database_csv: false,
          maybe_has_dataset_structure: true,
          readable: true,
        },
        {
          name: 'database.csv',
          path: '/data/database.csv',
          type: 'file',
          is_database_csv: true,
          maybe_has_dataset_structure: true,
          readable: true,
        },
      ],
    })
    mockedApi.validateWorkspaceSelection.mockResolvedValue({
      valid: true,
      activated: true,
      requires_dataset_root: false,
      workspace: activeWorkspace,
      summary: {
        dataset_id: 'DatasetLite',
        dataset_root: '/data/DatasetLite',
        database_csv_path: '/data/DatasetLite/database.csv',
        has_database: true,
        row_count: 2,
        case_count: 2,
        sampled_rows: 2,
        sampled_referenced_files: 4,
        sampled_existing_files: 4,
        has_nifti: true,
        has_seg: true,
        has_voi: true,
        has_manifest: false,
      },
      successes: [
        {
          code: 'csv_rows',
          message: 'Read 2 database rows.',
          severity: 'success',
          path: '/data/DatasetLite/database.csv',
        },
      ],
      warnings: [
        {
          code: 'seg_not_seen',
          message: 'SEG availability was not confirmed in the sample.',
          severity: 'warning',
          path: null,
        },
      ],
      errors: [],
    })
    mockedApi.listDatasets.mockResolvedValue([
      {
        dataset_id: 'DatasetLite',
        patient_count: 2,
        has_nifti: true,
        has_seg: true,
        has_voi: true,
        has_manifest: false,
      },
    ])
    mockedApi.listCases.mockResolvedValue([
      {
        case_id: 'case_00001',
        patient_id: 'case_00001',
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
    ])
    mockedApi.getDatabaseValidation.mockResolvedValue({
      dataset_id: 'DatasetLite',
      has_database: true,
      row_count: 2,
      case_count: 2,
      required_columns: [],
      warnings: [],
    })
    mockedApi.getSettings.mockResolvedValue({})
  })

  it('validates a manual backend path and opens review after activation', async () => {
    const user = userEvent.setup()
    renderSetup()

    expect(
      await screen.findByText('Host DATASET_DIR is mounted inside the app as /data.'),
    ).toBeInTheDocument()

    await user.type(
      screen.getByLabelText('Backend/server path, not local browser path'),
      '/data/DatasetLite',
    )
    await user.click(screen.getByRole('button', { name: 'Validate and Activate' }))

    expect(await screen.findByText('Warnings 1')).toBeInTheDocument()
    expect(screen.getByText('Errors 0')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'OK' }))

    await user.click(await screen.findByRole('button', { name: 'Start Review' }))
    expect(await screen.findByTestId('review-route')).toHaveTextContent('Review opened')
    expect(mockedApi.validateWorkspaceSelection).toHaveBeenCalledWith({
      dataset_folder_path: '/data/DatasetLite',
    })
  })

  it('selects database.csv from the backend browser and validates it', async () => {
    const user = userEvent.setup()
    renderSetup()

    await user.click(await screen.findByRole('button', { name: 'Browse database.csv' }))
    const dialog = await screen.findByRole('dialog', { name: 'Browse database.csv' })
    await user.click(within(dialog).getAllByText('database.csv')[0])
    await user.click(within(dialog).getByRole('button', { name: 'Select database.csv' }))

    await waitFor(() =>
      expect(mockedApi.validateWorkspaceSelection).toHaveBeenCalledWith({
        database_csv_path: '/data/database.csv',
      }),
    )
    expect(await screen.findByText('Success 1')).toBeInTheDocument()
  })
})

function renderSetup() {
  function Harness() {
    const [workspace, setWorkspace] = useState(emptyWorkspace)
    return (
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route
            path="/"
            element={
              <DatasetSelectorPage
                workspace={workspace}
                workspaceLoading={false}
                workspaceError={null}
                onWorkspaceChange={setWorkspace}
              />
            }
          />
          <Route
            path="/datasets/:datasetId/review/:caseId"
            element={<div data-testid="review-route">Review opened</div>}
          />
          <Route
            path="/datasets/:datasetId/review"
            element={<div data-testid="review-route">Review opened</div>}
          />
        </Routes>
      </MemoryRouter>
    )
  }

  return render(<Harness />)
}
