// @vitest-environment jsdom
// CUR-16 / API-66: the preview is read-only; only explicit confirmation sends a stamped write.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { registry } from '../../shell'
import { useReviewer } from '../../state'
import { RecycleScan } from './RecycleScan'

afterEach(() => { vi.restoreAllMocks(); registry.readOnly = false })

async function setup() {
  const item = (await api.getCase(DEMO_PID, 'case_00001')).items.find((i) => i.item_id === 'case_00001.01.complete.-')!
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onRecycled = vi.fn()
  render(<QueryClientProvider client={qc}><RecycleScan pid={DEMO_PID} item={item} onRecycled={onRecycled} /></QueryClientProvider>)
  return { item, onRecycled }
}

test('CUR-16 cancel leaves the CT intact; confirmation sends the preview token and reviewer', async () => {
  useReviewer.setState({ name: 'Dr. AP' })
  const preview = vi.spyOn(api, 'previewRecycle')
  const write = vi.spyOn(api, 'recycleScan')
  const { item, onRecycled } = await setup()
  fireEvent.click(screen.getByRole('button', { name: 'Move scan to recycle bin' }))
  let dialog = await screen.findByRole('dialog')
  expect(await within(dialog).findByText('/data/Dataset900/recycle_bin')).toBeInTheDocument()
  expect(preview).toHaveBeenCalledWith(DEMO_PID, item.item_id)
  expect(write).not.toHaveBeenCalled()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(write).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Move scan to recycle bin' }))
  dialog = await screen.findByRole('dialog')
  const confirm = within(dialog).getByRole('button', { name: 'Move scan to recycle bin' })
  await waitFor(() => expect(confirm).toBeEnabled())
  fireEvent.click(confirm)
  await waitFor(() => expect(write).toHaveBeenCalledWith(DEMO_PID, item.item_id, expect.any(String), 'Dr. AP'))
  await waitFor(() => expect(onRecycled).toHaveBeenCalledOnce())
})

test('CUR-16 the recycle button is hidden on view-only links', async () => {
  registry.readOnly = true
  await setup()
  expect(screen.queryByRole('button', { name: 'Move scan to recycle bin' })).not.toBeInTheDocument()
})
