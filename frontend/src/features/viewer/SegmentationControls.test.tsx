// @vitest-environment jsdom
// SRC-20 / VW-19: requests replay real recorded mask lifecycle exchanges.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import { api, type SegmentationInfo } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { SegmentationControls } from './SegmentationControls'

function controls(sets: SegmentationInfo[], active: string, onRemoved = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><SegmentationControls pid={DEMO_PID} sets={sets} active={active} itemId="case_00001.01.complete.-" onRemoved={onRemoved} /></QueryClientProvider>)
  return onRemoved
}

afterEach(() => vi.restoreAllMocks())

test('reimport starts with the removed set identity and asks for its source', async () => {
  const removed = await api.listSegmentations(DEMO_PID, true)
  controls(await api.listSegmentations(DEMO_PID), 'imported')
  fireEvent.click(await screen.findByRole('button', { name: 'Reimport' }))
  const dialog = screen.getByRole('dialog', { name: 'Import segmentation set' })
  expect(within(dialog).getByLabelText('Set ID')).toHaveValue(removed[0]!.seg_id)
  expect(within(dialog).getByLabelText('Display name')).toHaveValue(removed[0]!.name)
  expect(within(dialog).getByRole('button', { name: 'Import segmentation…' })).toBeDisabled()
})

test('restoring a removed set uses its recorded restore endpoint', async () => {
  const restore = vi.spyOn(api, 'restoreSegmentation')
  controls(await api.listSegmentations(DEMO_PID), 'imported')
  fireEvent.click(await screen.findByRole('button', { name: 'Restore' }))
  await waitFor(() => expect(restore).toHaveBeenCalledWith(DEMO_PID, 'reviewed'))
})

test('removal requires confirmation and updates the displayed selection after success', async () => {
  const restored = await api.restoreSegmentation(DEMO_PID, 'reviewed')
  const remove = vi.spyOn(api, 'removeSegmentation')
  const onRemoved = controls([restored], restored.seg_id)
  fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
  expect(remove).not.toHaveBeenCalled()
  const dialog = screen.getByRole('dialog', { name: 'Remove segmentation set' })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Remove' }))
  await waitFor(() => expect(remove).toHaveBeenCalledWith(DEMO_PID, 'reviewed'))
  await waitFor(() => expect(onRemoved).toHaveBeenCalledWith('reviewed'))
})
