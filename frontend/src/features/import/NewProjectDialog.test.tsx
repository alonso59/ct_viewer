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

test('retains the attached mask and adapter when the import root is the dataset itself', async () => {
  const prefill = { path: '/data/Dataset900', adapter: 'nifti-files' as const, options: { include: ['nifti/one.nii.gz'], masks: { 'nifti/one.nii.gz': 'seg/one.nii.gz' } } }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<MemoryRouter><QueryClientProvider client={qc}><NewProjectDialog open onOpenChange={vi.fn()} prefill={prefill} /></QueryClientProvider></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Project name'), { target: { value: 'Dataset project' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create and import' }))
  await waitFor(() => expect(useImportWizard.getState().prefill).toEqual(prefill))
})

test('opens with the latest source after a mask was attached while the dialog was closed', () => {
  const qc = new QueryClient()
  const dialog = (open: boolean, path: string) => <MemoryRouter><QueryClientProvider client={qc}><NewProjectDialog open={open} onOpenChange={vi.fn()} prefill={{ path }} /></QueryClientProvider></MemoryRouter>
  const view = render(dialog(false, '/data/Dataset900/nifti/one.nii.gz'))
  view.rerender(dialog(true, '/data/Dataset900'))
  expect(screen.getByLabelText('Dataset folder')).toHaveValue('/data/Dataset900')
})


test.each([
  { path: '/data/series/slice', kind: 'file' as const, root: '/data/series' },
  { path: '/data/study.dcm', kind: 'folder' as const, root: '/data/study.dcm' },
])('uses detected kind when choosing a project root for $path', ({ path, kind, root }) => {
  const qc = new QueryClient()
  render(<MemoryRouter><QueryClientProvider client={qc}><NewProjectDialog open onOpenChange={vi.fn()} prefill={{ path, kind }} /></QueryClientProvider></MemoryRouter>)
  expect(screen.getByLabelText('Dataset folder')).toHaveValue(root)
})
