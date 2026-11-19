// @vitest-environment jsdom
// CUR-17 / API-82: restore needs the preview token and a reviewer; a permanent delete needs the typed case ID.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useReviewer } from '../../state'
import RecycleBinPanel from './RecycleBinPanel'

afterEach(() => {
  vi.restoreAllMocks()
  useWorkbench.setState({ pid: null })
})

async function setup() {
  // The list is newest first, and the recorder's two recycles may share a second: creation order
  // (the recycle id) says which one the recording restores and which it deletes
  const entries = await api.listRecycleBin(DEMO_PID)
  const [restorable, deletable] = [...entries].sort((a, b) => a.recycle_id.localeCompare(b.recycle_id))
  useWorkbench.setState({ pid: DEMO_PID })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><RecycleBinPanel /></QueryClientProvider>)
  return { restorable: restorable!, deletable: deletable! }
}

test('CUR-17 restore previews first, and only confirmation sends the token and reviewer', async () => {
  useReviewer.setState({ name: 'Dr. AP' })
  const preview = vi.spyOn(api, 'previewRestore')
  const restore = vi.spyOn(api, 'restoreScan')
  const { restorable } = await setup()
  const scan = `${restorable.case_id} · ${restorable.scan_idx}`
  fireEvent.click(await screen.findByRole('button', { name: `Restore ${scan}` }))
  let dialog = await screen.findByRole('dialog')
  expect(await within(dialog).findByText(/3 files/)).toBeInTheDocument()
  expect(preview).toHaveBeenCalledWith(DEMO_PID, restorable.recycle_id)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(restore).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: `Restore ${scan}` }))
  dialog = await screen.findByRole('dialog')
  const confirm = within(dialog).getByRole('button', { name: 'Restore' })
  await waitFor(() => expect(confirm).toBeEnabled())
  fireEvent.click(confirm)
  await waitFor(() => expect(restore).toHaveBeenCalledWith(DEMO_PID, restorable.recycle_id, expect.any(String), 'Dr. AP'))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

test('CUR-17 permanent delete stays disabled until the case ID is typed', async () => {
  const remove = vi.spyOn(api, 'deleteRecycled')
  const { deletable } = await setup()
  const scan = `${deletable.case_id} · ${deletable.scan_idx}`
  fireEvent.click(await screen.findByRole('button', { name: `Delete ${scan} permanently` }))
  const dialog = await screen.findByRole('dialog')
  const confirm = within(dialog).getByRole('button', { name: 'Delete permanently' })
  expect(confirm).toBeDisabled()
  fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'case_00000' } })
  expect(confirm).toBeDisabled()
  fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: deletable.case_id } })
  expect(confirm).toBeEnabled()
  fireEvent.click(confirm)
  await waitFor(() => expect(remove).toHaveBeenCalledWith(DEMO_PID, deletable.recycle_id))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})
