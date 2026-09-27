// @vitest-environment jsdom
// AUD-A1-05 (LBL-01/03/04) on the recorded API (TST-04): the Inspector section shows the case /
// scan / item row of each table for the case on screen and writes cells with the table's editors.
// The recording has a case table "Review" (case_00001: Grade G1, Size 42) and a scan table "Phase check".
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useReviewer, useViewerSync } from '../../state'
import InspectorLabels, { targetOf } from './InspectorLabels'

test('targets follow the table level (LBL-01)', () => {
  const item = { item_id: 'c1.02.voi.L', scan_idx: '02' }
  expect(targetOf('case', 'c1', item)).toBe('c1')
  expect(targetOf('scan', 'c1', item)).toBe('c1.02')
  expect(targetOf('item', 'c1', item)).toBe('c1.02.voi.L')
  expect(targetOf('scan', 'c1', undefined)).toBeNull()
})

afterEach(() => vi.restoreAllMocks())

test('fills a case-level and a scan-level cell of the case on screen', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  useReviewer.setState({ name: 'Dr. T' })
  const write = vi.spyOn(api, 'writeLabelCells')
  const item = (await api.getCase(DEMO_PID, 'case_00001')).items.find((i) => i.status === 'active')!
  const tables = await api.listLabelTables(DEMO_PID)
  const review = tables.find((t) => t.name === 'Review')!
  const scanT = tables.find((t) => t.name === 'Phase check')!
  const col = (t: typeof review, name: string) => t.columns!.find((c) => c.name === name)!.column_id
  useViewerSync.setState({ activeCaseId: item.case_id, activeItemId: item.item_id })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <InspectorLabels />
    </QueryClientProvider>,
  )
  const patient = await screen.findByRole('group', { name: 'Review' })
  await waitFor(() => expect(within(patient).getByRole('button', { name: 'Edit Size' })).toHaveTextContent('42')) // the recorded value
  fireEvent.click(await within(patient).findByRole('checkbox', { name: 'Smoker' }))
  await waitFor(() => expect(write).toHaveBeenCalledWith(DEMO_PID, review.table_id, [{ column_id: col(review, 'Smoker'), target: item.case_id, value: true }], 'Dr. T'))

  const scan = await screen.findByRole('group', { name: 'Phase check' })
  fireEvent.click(await within(scan).findByRole('button', { name: 'Edit Mine' }))
  const input = within(scan).getByRole('textbox', { name: 'Mine' })
  fireEvent.change(input, { target: { value: 'motion' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  const target = `${item.case_id}.${item.scan_idx}`
  await waitFor(() => expect(write).toHaveBeenCalledWith(DEMO_PID, scanT.table_id, [{ column_id: col(scanT, 'Mine'), target, value: 'motion' }], 'Dr. T'))
})
