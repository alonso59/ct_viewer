// @vitest-environment jsdom
// UI-25 on the recorded API (TST-04): source → settings → dry run → run → result with the three
// next steps. The recording converted `dicom/P900` of the fixtures (one series, one scout).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import '../../i18n'
import '../../i18n/lazy'
import { api } from '../../api'
import { fmtBytes } from '../../lib'
import ConverterOverlay from './ConverterOverlay'
import { defaultDatasetName, useConverter } from './store'

test('converts a DICOM folder into a workspace dataset without a project', async () => {
  useConverter.getState().show({ source: '/data/dicom/P900', pid: null })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ConverterOverlay />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  // A prefilled source starts on Settings (Open mode on DICOM)
  expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('Settings')
  // AUD-A5-16 (NFR-17): the suggested name is neutral, never the (patient) folder name
  const name = defaultDatasetName()
  expect(screen.getByDisplayValue(name)).toBeInTheDocument()
  expect(screen.queryByDisplayValue('P900')).toBeNull()
  expect(screen.getByRole('checkbox', { name: /phase analyzer/ })).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'Dry run' }))
  const convert = await screen.findByRole('button', { name: 'Convert 1 series' })
  // DCM-06 (AUD-A2-13): which series is skipped and why; storage in the unit that fits
  expect(screen.getByText('2 series · 1 skipped')).toBeInTheDocument()
  expect(screen.getByText('Skip: localizer / scout')).toBeInTheDocument()
  expect(screen.getAllByText(fmtBytes(1512)).length).toBeGreaterThan(0)
  fireEvent.click(convert)
  fireEvent.click(await screen.findByRole('button', { name: 'Show the result' }))
  // the recorded run: its name and folder are the recording day's
  const [run] = await api.listWorkspaceRuns()
  expect(await screen.findByText(`Dataset ${run!.name} is ready.`)).toBeInTheDocument()
  expect(screen.getByText(run!.dataset_dir!)).toBeInTheDocument()
  for (const name of ['Open', 'Create project from this', 'Add to project']) expect(screen.getByRole('button', { name })).toBeInTheDocument()
})

test('a dataset name that is taken is said in the settings step (DCM-14, AUD-A2-14)', async () => {
  // the recorded workspace run holds a dataset name
  const [run] = await api.listWorkspaceRuns()
  const name = run!.name
  useConverter.getState().show({ source: '/data/dicom/P900', pid: null })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ConverterOverlay />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.change(screen.getByDisplayValue(defaultDatasetName()), { target: { value: name } })
  expect(await screen.findByText(`A dataset named ${name} exists; this one will be saved as ${name}-1.`)).toBeInTheDocument()
  fireEvent.change(screen.getByDisplayValue(name), { target: { value: 'fresh name' } })
  expect(screen.queryByText(/exists; this one will be saved/)).toBeNull()
})
