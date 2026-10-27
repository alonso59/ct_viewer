// @vitest-environment jsdom
// SRC-20/VW-19: label retirement targets one set value, independently of sets and catalogs.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import SegmentationPanel from './SegmentationPanel'

afterEach(() => {
  vi.restoreAllMocks()
  useWorkbench.setState({ pid: null })
  useViewerSync.setState({ segChoice: {} })
})

test('confirmation retires one label and leaves the whole set and catalog untouched', async () => {
  const change = vi.spyOn(api, 'setSegmentationLabelActive')
  const removeSet = vi.spyOn(api, 'removeSegmentation')
  const editCatalog = vi.spyOn(api, 'updateProject')
  const project = await api.getProject(DEMO_PID)
  const label = project.label_map.find((entry) => entry.value === 1)!
  useWorkbench.setState({ pid: DEMO_PID })
  useViewerSync.setState({ segChoice: {} })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><SegmentationPanel /></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: `Remove label ${label.name} from this set` }))
  expect(change).not.toHaveBeenCalled()
  const dialog = screen.getByRole('dialog', { name: 'Remove segmentation label' })
  expect(dialog).toHaveTextContent('for every case in this project')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Remove' }))
  await waitFor(() => expect(change).toHaveBeenCalledWith(DEMO_PID, 'imported', 1, false))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Remove segmentation label' })).not.toBeInTheDocument())
  expect(removeSet).not.toHaveBeenCalled()
  expect(editCatalog).not.toHaveBeenCalled()
})
