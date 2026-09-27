// @vitest-environment jsdom
// TST-19 UI half on the recorded API (LBL-01..04, TST-04): edit with the keyboard, paste a TSV
// block, see progress in the view; column and table edits send the right patch. The recording has
// the tables "Review" (case level), "Phase check" (scan level, a reference column) and a deleted
// "Scratch"; what the server does with a write is backend/tests/test_labeling.py.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import type { LabelTableInfo } from '../../api'
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

// the layout spies of beforeAll stay; each test restores its own API spies
const spies: { mockRestore(): void }[] = []
afterEach(() => spies.splice(0).forEach((s) => s.mockRestore()))

const table = async (name: string): Promise<LabelTableInfo> => {
  const t = [...(await api.listLabelTables(DEMO_PID)), ...(await api.listLabelTables(DEMO_PID, true))].find((x) => x.name === name)
  if (!t) throw new Error(`recorded table ${name} missing`)
  return t
}
const col = (t: LabelTableInfo, name: string) => t.columns!.find((c) => c.name === name)!.column_id

test('keyboard edit, paste and progress', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  useReviewer.setState({ name: 'Dr. T' })
  const write = vi.spyOn(api, 'writeLabelCells')
  spies.push(write)
  const t = await table('Review')
  const view = wrap(<TableEditor params={{ tableId: t.table_id }} panelId="p" active />)
  const grid = await screen.findByRole('grid', { name: 'Review' })
  await screen.findAllByRole('row')
  const [first, second] = (await screen.findAllByRole('rowheader')).map((h) => (h.textContent ?? '').trim())
  // Typing on the active cell opens the editor; Enter commits
  act(() => grid.focus())
  fireEvent.keyDown(grid, { key: 'ArrowRight' })
  fireEvent.keyDown(grid, { key: '4' })
  const input = await screen.findByRole('spinbutton', { name: 'Size' })
  fireEvent.change(input, { target: { value: '43' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  // one write per edit (the blur after Enter does not write again); the server coerces the text
  await waitFor(() => expect(write).toHaveBeenCalledWith(DEMO_PID, t.table_id, [{ column_id: col(t, 'Size'), target: first, value: '43' }], 'Dr. T'))
  expect(write).toHaveBeenCalledTimes(1)
  // Paste two rows × one column at the first cell
  fireEvent.keyDown(grid, { key: 'ArrowUp' })
  fireEvent.keyDown(grid, { key: 'ArrowLeft' })
  fireEvent.paste(grid, { clipboardData: { getData: () => 'G2\nG1\n' } })
  await waitFor(() =>
    expect(write).toHaveBeenLastCalledWith(DEMO_PID, t.table_id, [{ column_id: col(t, 'Grade'), target: first, value: 'G2' }, { column_id: col(t, 'Grade'), target: second, value: 'G1' }], 'Dr. T'),
  )
  view.unmount()
  // the view's progress is the server's (the recording filled Grade on two cases)
  wrap(<LabelingView />)
  const card = (await screen.findByText('Review')).closest('button') as HTMLElement
  expect(within(card).getByText(/Grade: 2 \//)).toBeInTheDocument()
})

test('LBL-02/10: edit and delete a column, delete a table, restore one', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  const patch = vi.spyOn(api, 'patchLabelTable')
  spies.push(patch)
  const t = await table('Review')
  const menu = async (label: string, item: string) => {
    fireEvent.keyDown(await screen.findByRole('button', { name: label }), { key: 'Enter' })
    fireEvent.click(await screen.findByRole('menuitem', { name: item }))
  }
  const editor = wrap(<TableEditor params={{ tableId: t.table_id }} panelId="p" active />)
  await screen.findByRole('grid', { name: 'Review' })
  await screen.findAllByRole('rowheader') // the cells have loaded
  // Edit column: rename, change the unit, clear the max
  await menu('Actions for column Size', 'Edit column…')
  const dlg = await screen.findByRole('dialog', { name: 'Edit column' })
  fireEvent.change(within(dlg).getByLabelText(/^Column name/), { target: { value: 'Diameter' } })
  fireEvent.change(within(dlg).getByLabelText(/^Unit/), { target: { value: 'cm' } })
  fireEvent.change(within(dlg).getByLabelText(/^Max/), { target: { value: '' } })
  fireEvent.click(within(dlg).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(patch).toHaveBeenCalledWith(DEMO_PID, t.table_id, { columns: [expect.objectContaining({ column_id: col(t, 'Size'), name: 'Diameter', unit: 'cm', max: null })] }))
  // Delete column: hidden, not erased
  await menu('Actions for column Note', 'Delete column…')
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Delete column Note?' })).getByRole('button', { name: 'Delete column' }))
  await waitFor(() => expect(patch).toHaveBeenLastCalledWith(DEMO_PID, t.table_id, { columns: [expect.objectContaining({ column_id: col(t, 'Note'), hidden: true })] }))
  // Delete the table from its tab
  await menu('Actions for table Review', 'Delete table…')
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Delete Review?' })).getByRole('button', { name: 'Delete table' }))
  await waitFor(() => expect(patch).toHaveBeenLastCalledWith(DEMO_PID, t.table_id, expect.objectContaining({ hidden: true })))
  editor.unmount()
  // The view lists the recorded deleted table; Restore brings it back
  const scratch = await table('Scratch')
  wrap(<LabelingView />)
  fireEvent.click(await screen.findByRole('button', { name: /Deleted tables \(1\)/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Restore' }))
  await waitFor(() => expect(patch).toHaveBeenLastCalledWith(DEMO_PID, scratch.table_id, expect.objectContaining({ hidden: false })))
})

test('LBL-09: a reference column mirrors the effective phase and stays read-only', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  useReviewer.setState({ name: 'Dr. T' })
  const t = await table('Phase check')
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
  // the server refuses a write to it (the recorded 422)
  await expect(api.writeLabelCells(DEMO_PID, t.table_id, [{ column_id: ref.column_id, target: first.target, value: 'NC' }], 'Dr. T')).rejects.toMatchObject({ status: 422 })
  // the add-column form offers it as a type once comparable variables exist
  fireEvent.click(screen.getByRole('button', { name: 'Add column' }))
  const dlg = await screen.findByRole('dialog', { name: 'Add column' })
  fireEvent.change(within(dlg).getByRole('combobox', { name: 'Type' }), { target: { value: 'ref' } })
  expect(await within(dlg).findByRole('option', { name: 'phase.effective' })).toBeInTheDocument()
  view.unmount()
})
