// AUD-A1-05 (LBL-01/03/04) on the mock API: the Inspector section shows the case / scan / item row
// of each table for the case on screen and writes cells with the table's editors.
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

test('fills a case-level and a scan-level cell of the case on screen', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  useReviewer.setState({ name: 'Dr. T' })
  const cases = await api.listCases(DEMO_PID)
  const detail = await api.getCase(DEMO_PID, cases[0]!.case_id)
  const item = detail.items.find((i) => i.status === 'active')!
  const caseT = await api.createLabelTable(DEMO_PID, { name: 'Patient', level: 'case', columns: [{ name: 'Smoker', type: 'bool' }] })
  const scanT = await api.createLabelTable(DEMO_PID, { name: 'Scan QC', level: 'scan', columns: [{ name: 'Note', type: 'text' }] })
  useViewerSync.setState({ activeCaseId: item.case_id, activeItemId: item.item_id })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <InspectorLabels />
    </QueryClientProvider>,
  )
  const patient = await screen.findByRole('group', { name: 'Patient' })
  fireEvent.click(await within(patient).findByRole('checkbox', { name: 'Smoker' }))
  await waitFor(async () => expect((await api.labelCells(DEMO_PID, caseT.table_id)).items.find((r) => r.target === item.case_id)?.values?.[caseT.columns![0]!.column_id]).toBe(true))

  const scan = await screen.findByRole('group', { name: 'Scan QC' })
  fireEvent.click(await within(scan).findByRole('button', { name: 'Edit Note' }))
  const input = within(scan).getByRole('textbox', { name: 'Note' })
  fireEvent.change(input, { target: { value: 'motion' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  const target = `${item.case_id}.${item.scan_idx}`
  await waitFor(async () => expect((await api.labelCells(DEMO_PID, scanT.table_id)).items.find((r) => r.target === target)?.values?.[scanT.columns![0]!.column_id]).toBe('motion'))
})
