// @vitest-environment jsdom
// AUD-A1-16 (API-10, SRC-09): a filter for long folders, type-to-select, no Parent row at a root.
// On the recorded fixtures (TST-04) the shared folders are the data root and the workspace datasets.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { vi } from 'vitest'

import '../../i18n'
import { api } from '../../api'
import { FolderBrowser } from './FolderBrowser'

function Host({ start }: { start: string }) {
  const [path, setPath] = useState<string | null>(start)
  return <FolderBrowser path={path} onPath={setPath} onSelectFile={() => undefined} />
}

const wrap = (start: string) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Host start={start} />
    </QueryClientProvider>,
  )

test('a shared root has no Parent row; with several shared folders it leads to their list', async () => {
  wrap('/data')
  expect(await screen.findByRole('button', { name: /Dataset900/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Parent folder' })).toBeNull()
  expect(screen.getByRole('button', { name: 'All shared folders' })).toBeInTheDocument()
})

test('a long folder gets a filter box and type-to-select', async () => {
  wrap('/data/Dataset900/nifti')
  const filter = await screen.findByRole('searchbox', { name: 'Filter this folder' })
  expect(screen.getByRole('button', { name: 'Parent folder' })).toBeInTheDocument()
  fireEvent.change(filter, { target: { value: '00017' } })
  expect(screen.getAllByRole('button', { name: /_0000\.nii\.gz$/ }).map((b) => b.textContent)).toEqual(['01_case_00017_0000.nii.gz'])
  fireEvent.change(filter, { target: { value: '' } })
  const list = screen.getByRole('listbox', { name: 'Folders' })
  fireEvent.keyDown(list, { key: '0' })
  expect(document.activeElement?.textContent).toBe('01_case_00001_0000.nii.gz') // the folder's first file
})

test('SRC-18 content discovery can select unknown suffixes while directories use server kind', async () => {
  const sample = await api.fsList('/data')
  const first = sample.entries[0]!
  const listing = { ...sample, path: '/data/series', parent: '/data', entries: [
    { ...first, name: 'slice.001', path: '/data/series/slice.001', kind: 'file' as const },
    { ...first, name: 'image', path: '/data/series/image', kind: 'file' as const },
    { ...first, name: 'study.dcm', path: '/data/series/study.dcm', kind: 'dir' as const },
  ] }
  vi.spyOn(api, 'fsList').mockResolvedValue(listing)
  const pick = vi.fn()
  const navigate = vi.fn()
  try {
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <FolderBrowser path="/data/series" onPath={navigate} onSelectFile={pick} fileFilter={() => true} />
    </QueryClientProvider>)
    const slice = await screen.findByRole('button', { name: /slice\.001/ })
    expect(slice).toBeEnabled()
    fireEvent.click(slice)
    fireEvent.click(screen.getByRole('button', { name: /^image/ }))
    expect(pick.mock.calls.map(([path]) => path)).toEqual(['/data/series/slice.001', '/data/series/image'])
    fireEvent.click(screen.getByRole('button', { name: /study\.dcm/ }))
    expect(navigate).toHaveBeenCalledWith('/data/series/study.dcm')
  } finally { vi.restoreAllMocks() }
})
