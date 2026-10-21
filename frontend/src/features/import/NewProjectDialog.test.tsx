// @vitest-environment jsdom
// PRJ-19: creating a project chooses dataset-local state and results.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import '../../i18n'
import { api } from '../../api'
import { NewProjectDialog } from './NewProjectDialog'
import { useImportWizard } from './store'

afterEach(() => vi.restoreAllMocks())

test('PRJ-19 requires a dataset folder and forwards it to create and import', async () => {
  const create = vi.spyOn(api, 'createProject')
  const close = vi.fn()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<MemoryRouter><QueryClientProvider client={qc}><NewProjectDialog open onOpenChange={close} /></QueryClientProvider></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Project name'), { target: { value: 'Dataset project' } })
  const submit = screen.getByRole('button', { name: 'Create and import' })
  expect(submit).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Dataset folder'), { target: { value: '/data/Dataset900' } })
  fireEvent.click(submit)
  await waitFor(() => expect(create).toHaveBeenCalledWith({ name: 'Dataset project', default_modality: 'CT', dataset_root: '/data/Dataset900' }))
  await waitFor(() => expect(close).toHaveBeenCalledWith(false))
  expect(useImportWizard.getState().prefill?.path).toBe('/data/Dataset900')
})
