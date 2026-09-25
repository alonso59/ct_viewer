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

test('LBL-02/10: edit and delete a column, delete a table, restore both', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  const t = await api.createLabelTable(DEMO_PID, { name: 'Scratch', level: 'case', columns: [{ name: 'Size', type: 'number', unit: 'mm', max: 10 }, { name: 'Note', type: 'text' }] })
  const size = t.columns![0]!.column_id
  const menu = async (label: string, item: string) => {
    fireEvent.keyDown(await screen.findByRole('button', { name: label }), { key: 'Enter' })
    fireEvent.click(await screen.findByRole('menuitem', { name: item }))
  }
  const editor = wrap(<TableEditor params={{ tableId: t.table_id }} panelId="p" active />)
  await screen.findByRole('grid', { name: 'Scratch' })
  // Edit column: rename, change the unit, clear the max
  await menu('Actions for column Size', 'Edit column…')
  const dlg = await screen.findByRole('dialog', { name: 'Edit column' })
  fireEvent.change(within(dlg).getByLabelText(/^Column name/), { target: { value: 'Diameter' } })
  fireEvent.change(within(dlg).getByLabelText(/^Unit/), { target: { value: 'cm' } })
  fireEvent.change(within(dlg).getByLabelText(/^Max/), { target: { value: '' } })
  fireEvent.click(within(dlg).getByRole('button', { name: 'Save' }))
  await waitFor(async () => expect((await api.listLabelTables(DEMO_PID)).find((x) => x.table_id === t.table_id)?.columns?.[0]).toMatchObject({ name: 'Diameter', unit: 'cm', max: null }))
  // Delete column: hidden, not erased
  await menu('Actions for column Note', 'Delete column…')
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Delete column Note?' })).getByRole('button', { name: 'Delete column' }))
  await waitFor(() => expect(screen.queryByRole('columnheader', { name: /Note/ })).toBeNull())
  // Delete the table from its tab: the tab says so
  await menu('Actions for table Scratch', 'Delete table…')
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Delete Scratch?' })).getByRole('button', { name: 'Delete table' }))
  expect(await screen.findByText(/This table was deleted/)).toBeInTheDocument()
  expect((await api.listLabelTables(DEMO_PID)).some((x) => x.table_id === t.table_id)).toBe(false)
  editor.unmount()
  // The view lists it under Deleted tables; Restore brings it back with its size column
  wrap(<LabelingView />)
  fireEvent.click(await screen.findByRole('button', { name: /Deleted tables \(1\)/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Restore' }))
  expect(await screen.findByRole('button', { name: /^Scratch/ })).toBeInTheDocument()
  const back = (await api.listLabelTables(DEMO_PID)).find((x) => x.table_id === t.table_id)
  expect(back?.columns?.map((c) => [c.name, c.hidden])).toEqual([['Diameter', false], ['Note', true]])
  await api.patchLabelTable(DEMO_PID, t.table_id, { columns: [{ column_id: size, name: 'Diameter' }] })
})

test('LBL-09: a reference column mirrors the effective phase and stays read-only', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  useReviewer.setState({ name: 'Dr. T' })
  const t = await api.createLabelTable(DEMO_PID, { name: 'Phase check', level: 'scan', columns: [{ name: 'App phase', ref: 'phase.effective' }, { name: 'Mine', type: 'text' }] })
  const ref = t.columns![0]!
  expect(ref.ref).toBe('phase.effective')
  const first = (await api.labelCells(DEMO_PID, t.table_id)).items[0]!
  const item = (await api.getCase(DEMO_PID, first.case_id)).items.find((i) => i.item_id === first.item_id)!
  const view = wrap(<TableEditor params={{ tableId: t.table_id }} panelId="p" active />)
  const grid = await screen.findByRole('grid', { name: 'Phase check' })
  const cells = await screen.findAllByRole('gridcell')
  await waitFor(() => expect(cells[0]).toHaveTextContent(item.phase.canonical))
  expect(cells[0]).toHaveAttribute('aria-readonly', 'true')
  // typing on the reference cell opens no editor, and nothing is written
  act(() => grid.focus())
  fireEvent.keyDown(grid, { key: 'N' })
  expect(screen.queryByRole('textbox', { name: 'App phase' })).toBeNull()
  await expect(api.writeLabelCells(DEMO_PID, t.table_id, [{ column_id: ref.column_id, target: first.target, value: 'NC' }], 'Dr. T')).rejects.toThrow()
  // the add-column form offers it as a type once comparable variables exist
  fireEvent.click(screen.getByRole('button', { name: 'Add column' }))
  const dlg = await screen.findByRole('dialog', { name: 'Add column' })
  fireEvent.change(within(dlg).getByRole('combobox', { name: 'Type' }), { target: { value: 'ref' } })
  expect(await within(dlg).findByRole('option', { name: 'phase.effective' })).toBeInTheDocument()
  view.unmount()
})
