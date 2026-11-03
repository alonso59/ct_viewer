// @vitest-environment jsdom
// CUR-09: the queue table sorts by a column (aria-sort on its header), tells a filter that hides
// every row from an empty queue, and offers Export shown next to Export all while filtered.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { keys, type QueueRow } from '../../api'
import { useWorkbench } from '../../shell'
import { QueueEditor } from './QueueEditor'

const PID = 'queue-test'
const row = (caseId: string, status: QueueRow['status'], priority: QueueRow['priority']) =>
  ({ case_id: caseId, item_id: `${caseId}.01.complete.-`, phase: null, scope: 'complete', side: null, target: 'seg', seg_id: 'imported', status, priority, comment: '', reviewer: 'ana', at: '2026-11-01T10:00:00Z', image_path_abs: null, mask_path_abs: null }) as QueueRow

function queue(rows: QueueRow[]) {
  useWorkbench.setState({ pid: PID })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.queue(PID), rows)
  render(<QueryClientProvider client={qc}><QueueEditor /></QueryClientProvider>)
}

afterEach(() => useWorkbench.setState({ pid: null }))

test('a header sorts its column both ways and says so', () => {
  queue([row('case_00002', 'rejected', 'low'), row('case_00001', 'needs_major_correction', 'high')])
  const cases = () => screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[0]?.textContent)
  const header = screen.getByRole('columnheader', { name: /Case/ })
  fireEvent.click(within(header).getByRole('button'))
  expect(header).toHaveAttribute('aria-sort', 'ascending')
  expect(cases()).toEqual(['case_00001', 'case_00002'])
  fireEvent.click(within(header).getByRole('button'))
  expect(header).toHaveAttribute('aria-sort', 'descending')
  expect(cases()).toEqual(['case_00002', 'case_00001'])
})

test('a status filter that hides every row is not an empty queue; Export shown appears while filtered', () => {
  queue([row('case_00001', 'rejected', 'medium')])
  expect(screen.queryByRole('button', { name: /Export shown/ })).toBeNull()
  fireEvent.change(screen.getByRole('combobox', { name: 'Curation status' }), { target: { value: 'needs_minor_correction' } })
  expect(screen.getByText('No queued item has this status.')).toBeInTheDocument()
  expect(screen.queryByText('The correction queue is empty')).toBeNull()
  expect(screen.getByRole('button', { name: /Export shown/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Export CSV for 3D Slicer' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Show all statuses' }))
  expect(screen.getAllByRole('row')).toHaveLength(2)
})
