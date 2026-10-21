// @vitest-environment jsdom
// PRJ-19 / API-67: open a saved project by choosing its dataset folder.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import '../../i18n'
import { api } from '../../api'
import { OpenDatasetDialog } from './OpenDatasetDialog'

afterEach(() => vi.restoreAllMocks())

test('PRJ-19 opens the saved project through the real recorded API contract', async () => {
  const open = vi.spyOn(api, 'openDataset')
  const close = vi.fn()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<MemoryRouter><QueryClientProvider client={qc}><OpenDatasetDialog onClose={close} /></QueryClientProvider></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Dataset folder'), { target: { value: '/data/Dataset900' } })
  fireEvent.click(screen.getByRole('button', { name: 'Open dataset project…' }))
  await waitFor(() => expect(open).toHaveBeenCalledWith('/data/Dataset900'))
  await waitFor(() => expect(close).toHaveBeenCalledOnce())
})
