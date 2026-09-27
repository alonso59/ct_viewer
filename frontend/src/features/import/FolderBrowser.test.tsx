// @vitest-environment jsdom
// AUD-A1-16 (API-10, SRC-09): a filter for long folders, type-to-select, no Parent row at a root.
// On the recorded fixtures (TST-04) the shared folders are the data root and the workspace datasets.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import '../../i18n'
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
