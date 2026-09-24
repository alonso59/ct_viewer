// TST-19 UI half on the mock API (LBL-01..04): create a table, edit with the keyboard, paste a TSV
// block, see progress in the view.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useReviewer } from '../../state'
import LabelingView from './LabelingView'
import TableEditor from './TableEditor'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

// jsdom has no layout: give elements a size so the virtualized rows render
beforeAll(() => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => ({}) } as DOMRect)
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 600 })
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get: () => 800 })
})

test('keyboard edit, paste and progress', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  useReviewer.setState({ name: 'Dr. T' })
  const t = await api.createLabelTable(DEMO_PID, { name: 'Review', level: 'case', columns: [{ name: 'Grade', type: 'category', levels: ['G1', 'G2'] }, { name: 'Size', type: 'number' }] })
  const view = wrap(<TableEditor params={{ tableId: t.table_id }} panelId="p" active />)
  const grid = await screen.findByRole('grid', { name: 'Review' })
  await screen.findAllByRole('row')
  const first = (await screen.findAllByRole('rowheader'))[0]!.textContent ?? ''
  // Typing on the active cell opens the editor; Enter commits
  act(() => grid.focus())
  fireEvent.keyDown(grid, { key: 'ArrowRight' })
  fireEvent.keyDown(grid, { key: '4' })
  const input = await screen.findByRole('spinbutton', { name: 'Size' })
  fireEvent.change(input, { target: { value: '42' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  await waitFor(async () => expect((await api.labelCells(DEMO_PID, t.table_id)).items.find((r) => r.target === first.trim())?.values?.[t.columns![1]!.column_id]).toBe(42))
  // Paste two rows × one column at the first cell
  fireEvent.keyDown(grid, { key: 'ArrowUp' })
  fireEvent.keyDown(grid, { key: 'ArrowLeft' })
  fireEvent.paste(grid, { clipboardData: { getData: () => 'G1\nG2\n' } })
  await waitFor(async () => {
    const rows = (await api.labelCells(DEMO_PID, t.table_id)).items
    expect(rows.slice(0, 2).map((r) => r.values?.[t.columns![0]!.column_id])).toEqual(['G1', 'G2'])
  })
  view.unmount()
  wrap(<LabelingView />)
  const card = (await screen.findByText('Review')).closest('button') as HTMLElement
  expect(within(card).getByText(/Grade: 2 \//)).toBeInTheDocument()
})
