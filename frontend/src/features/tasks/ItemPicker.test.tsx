// @vitest-environment jsdom
// TSK-03: grouping is indexed case identity; filters never silently change selected IDs.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'

import '../../i18n'
import '../../i18n/lazy'
import { api, type ItemFilter, type ItemPage } from '../../api'
import { ItemPicker } from './ItemPicker'

afterEach(() => vi.restoreAllMocks())

const rows = [
  { item_id: 'subject-x.01.complete.-', case_id: 'subject-x', scan_idx: '01', scope: 'complete', modality: 'CT', phase: { canonical: 'arterial' }, image: { ref: 'DATA:one.nii.gz' }, masks: {} },
  { item_id: 'subject-x.02.complete.-', case_id: 'subject-x', scan_idx: '02', scope: 'complete', modality: 'MR', phase: { canonical: 'delayed' }, image: { ref: 'DATA:another-name.nii.gz' }, masks: { organ: {} } },
]

function show(initial = '') {
  function Controlled() {
    const [value, onChange] = useState(initial)
    return <ItemPicker pid="p" value={value} onChange={onChange} />
  }
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Controlled /></QueryClientProvider>)
}

test('case selection uses exact IDs and manual selection stays visible across pages and filters', async () => {
  const list = vi.spyOn(api, 'listItems').mockImplementation(async (_pid, f?: ItemFilter) => ({
    items: f?.q ? [] : f?.cursor ? [rows[1]] : rows,
    total: 3, next_cursor: f?.cursor || f?.q ? null : '2',
  }) as ItemPage)
  show('previous.01.complete.-')
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Select case subject-x on this page' }))
  expect(screen.getByText('3 selected')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
  await waitFor(() => expect(list).toHaveBeenLastCalledWith('p', expect.objectContaining({ cursor: '2' })))
  expect(await screen.findByRole('checkbox', { name: 'Select file another-name.nii.gz' })).toBeChecked()
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search files or cases' }), { target: { value: 'no-match' } })
  expect(await screen.findByText('No files match these filters.')).toBeInTheDocument()
  expect(screen.getByText('3 selected')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Paste or edit item IDs'))
  expect(screen.getByPlaceholderText('Item ids, separated by spaces, commas or new lines')).toHaveValue('previous.01.complete.-\nsubject-x.01.complete.-\nsubject-x.02.complete.-')
  fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))
  expect(screen.getByText('0 selected')).toBeInTheDocument()
})

test('a failed item listing is reported and never erases the explicit selection', async () => {
  vi.spyOn(api, 'listItems').mockRejectedValue(new Error('index is unavailable'))
  show(rows[0]!.item_id)
  expect(await screen.findByText('index is unavailable')).toBeInTheDocument()
  expect(screen.getByText('1 selected')).toBeInTheDocument()
})

test('select all matching files includes other pages and preserves selections outside the filter', async () => {
  vi.spyOn(api, 'listItems').mockResolvedValue({ items: rows, total: 3, next_cursor: '2' } as ItemPage)
  const ids = [...rows.map((row) => row.item_id), 'subject-y.01.complete.-']
  const resolve = vi.spyOn(api, 'listItemIds').mockResolvedValue(ids)
  show('outside.01.complete.-')
  const all = await screen.findByRole('checkbox', { name: 'Select all matching files' })
  fireEvent.click(all)
  expect(await screen.findByText('4 selected')).toBeInTheDocument()
  expect(all).toBeChecked()
  expect(resolve).toHaveBeenCalledWith('p', {})
  fireEvent.click(all)
  expect(await screen.findByText('1 selected')).toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox', { name: 'Rows per page' }), { target: { value: '500' } })
  await waitFor(() => expect(api.listItems).toHaveBeenLastCalledWith('p', expect.objectContaining({ limit: 500, cursor: undefined })))
})

test('a failed select-all leaves the prior selection intact and unlocks the picker', async () => {
  vi.spyOn(api, 'listItems').mockResolvedValue({ items: rows, total: 3, next_cursor: null } as ItemPage)
  vi.spyOn(api, 'listItemIds').mockRejectedValue(new Error('selection lookup failed'))
  show('outside.01.complete.-')
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Select all matching files' }))
  expect(await screen.findByText('selection lookup failed')).toBeInTheDocument()
  expect(screen.getByText('1 selected')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Clear selection' })).toBeEnabled()
})

test('select all shows the requested checkbox state while the matching IDs load', async () => {
  vi.spyOn(api, 'listItems').mockResolvedValue({ items: rows, total: 3, next_cursor: null } as ItemPage)
  let finish: (ids: string[]) => void = () => { throw new Error('No pending request') }
  vi.spyOn(api, 'listItemIds').mockImplementation(() => new Promise<string[]>((resolve) => { finish = resolve }))
  show()
  const all = await screen.findByRole('checkbox', { name: 'Select all matching files' })
  await waitFor(() => expect(all).toBeEnabled())
  fireEvent.click(all)
  expect(all).toBeChecked()
  expect(all).toBeDisabled()
  await act(async () => finish([...rows.map((r) => r.item_id), 'third.01.complete.-']))
  expect(await screen.findByText('3 selected')).toBeInTheDocument()
  expect(all).toBeChecked()
  expect(all).toBeEnabled()
})

test('search disables selection of the previous page until the matching page arrives', async () => {
  vi.spyOn(api, 'listItems').mockImplementation(async (_pid, filter?: ItemFilter) => ({
    items: filter?.q ? [rows[1]] : rows, total: filter?.q ? 1 : 2, next_cursor: null,
  }) as ItemPage)
  show()
  const header = await screen.findByRole('checkbox', { name: 'Select files on this page' })
  await waitFor(() => expect(header).toBeEnabled())
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search files or cases' }), { target: { value: 'another-name' } })
  expect(header).toBeDisabled()
  await waitFor(() => expect(screen.queryByRole('checkbox', { name: 'Select file one.nii.gz' })).not.toBeInTheDocument())
  await waitFor(() => expect(header).toBeEnabled())
  fireEvent.click(header)
  expect(screen.getByText('1 selected')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Paste or edit item IDs'))
  expect(screen.getByRole('textbox', { name: 'Paste or edit item IDs' })).toHaveValue(rows[1]!.item_id)
})
