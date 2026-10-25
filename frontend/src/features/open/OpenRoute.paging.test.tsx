// @vitest-environment jsdom
// U08/D09, SRC-18/10/14: actual recorded mixed-file pages retain later selections.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { api, type ItemRecord } from '../../api'
import OpenRoute from './OpenRoute'

// The WebGL renderer is the boundary; requests, wire data, selection and dialogs stay real.
vi.mock('../viewer', () => ({
  CtToolbar: () => null,
  ModalityChip: () => null,
  resetDisplay: () => undefined,
  StandaloneViewer: ({ item }: { item: ItemRecord }) => <div data-testid="selected-volume" data-item={item.item_id} data-mask={item.mask?.ref ?? ''} />,
}))

afterEach(() => vi.restoreAllMocks())

test('pages beyond 500 keep the selected volume and its latest overlay when paging and saving', async () => {
  localStorage.clear()
  const opened = await api.openPath('/open-data/images')
  const save = vi.spyOn(api, 'saveOpen')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[`/open/${opened.sid}`]}><Routes><Route path="/open/:sid" element={<OpenRoute />} /></Routes></MemoryRouter></QueryClientProvider>)
  const list = await screen.findByRole('listbox', { name: 'Files' })
  expect(within(list).getAllByRole('button')).toHaveLength(50)
  expect(screen.getByRole('button', { name: 'Convert DICOM…' })).toBeVisible()
  for (let page = 1; page <= 10; page++) {
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next page' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    await waitFor(() => expect(within(list).getAllByRole('button')[0]).toHaveTextContent(`${String(page * 50).padStart(4, '0')}.nii.gz`))
  }
  expect(within(list).getAllByRole('button')).toHaveLength(4)
  expect(screen.getByTestId('selected-volume')).toHaveAttribute('data-item', 'open.0')
  fireEvent.click(within(list).getByRole('button', { name: '0502.nii.gz' }))
  await waitFor(() => expect(screen.getByTestId('selected-volume')).toHaveAttribute('data-item', 'open.502'))
  expect(screen.getByTestId('selected-volume')).toHaveAttribute('data-mask', '/open-data/masks/mask2.nii.gz')
  fireEvent.click(screen.getByRole('button', { name: 'Previous page' }))
  await waitFor(() => expect(within(list).getAllByRole('button')[0]).toHaveTextContent('0450.nii.gz'))
  expect(screen.getByTestId('selected-volume')).toHaveAttribute('data-item', 'open.502')
  fireEvent.click(screen.getByRole('button', { name: 'Save as NIfTI…' }))
  const dialog = await screen.findByRole('dialog', { name: 'Save 0502.nii.gz as NIfTI' })
  fireEvent.click(within(dialog).getByRole('button', { name: /^Save$/ }))
  await waitFor(() => expect(save).toHaveBeenCalledWith(opened.sid, 502, { dest_dir: null, sidecar: false, anonymize: 'none', axis_order: null }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})
