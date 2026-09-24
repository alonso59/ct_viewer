// UI-25 on the mock API: source → settings → dry run → run → result with the three next steps.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import '../../i18n'
import '../../i18n/lazy'
import ConverterOverlay from './ConverterOverlay'
import { useConverter } from './store'

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
  expect(screen.getByDisplayValue('P900')).toBeInTheDocument()
  expect(screen.getByRole('checkbox', { name: /phase analyzer/ })).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'Dry run' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Convert 2 series' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Show the result' }))
  expect(await screen.findByText('Dataset P900 is ready.')).toBeInTheDocument()
  expect(screen.getByText('/mock/derived/_datasets/P900')).toBeInTheDocument()
  for (const name of ['Open', 'Create project from this', 'Add to project']) expect(screen.getByRole('button', { name })).toBeInTheDocument()
})
