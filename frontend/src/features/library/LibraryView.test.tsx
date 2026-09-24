// TST-17 (PLG-05/06/09, UI-22): the Library lists every plugin with status; pending ones cannot open.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { useLayout } from '../../state'
import { activatePlugins, FIRST_PARTY } from '../../plugins'
import LibraryView, { PluginCard } from './LibraryView'

test('lists the shipped plugins; Open reveals a ready plugin; pending plugins are disabled', async () => {
  activatePlugins(FIRST_PARTY)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const { container } = render(
    <QueryClientProvider client={qc}>
      <LibraryView />
    </QueryClientProvider>,
  )
  await screen.findByText('Curation & QC')
  const card = (id: string) => container.querySelector(`[data-plugin="${id}"]`) as HTMLElement
  for (const id of ['dicom', 'analyzers', 'curation', 'radiomics', 'dashboard', 'nnunet', 'voi']) expect(card(id)).not.toBeNull()
  expect(within(card('nnunet')).getByText('pending')).toBeInTheDocument()
  expect(within(card('nnunet')).getByRole('button', { name: 'Open nnU-Net segmentation' })).toBeDisabled()
  expect(within(card('voi')).getByRole('button', { name: /Open VOI/ })).toBeDisabled()
  useLayout.getState().set({ activeView: 'project' })
  fireEvent.click(within(card('curation')).getByRole('button', { name: 'Open Curation & QC' }))
  expect(useLayout.getState().activeView).toBe('curation')
})

test('a card shows the status reason and what the plugin adds', () => {
  render(
    <PluginCard
      info={{
        manifest: {
          plugin: 1, id: 'dicom', version: '1.0.0', title: 'DICOM converter', description: 'd', icon: 'file-binary', scope: 'workspace',
          contributes: { tasks: ['dicom.convert'], views: [], editors: [], overlays: [], panels: [], commands: ['c'], columns: [], packs: [] },
          requires: { core: '>=3.0', plugins: [], capabilities: ['derived_root'] }, pending: false, hidden: false,
        },
        status: 'needs_derived_root',
        reason: 'Writes volumes: set ALLOWED_DERIVED_ROOTS',
        actions: [],
      }}
    />,
  )
  expect(screen.getByText('needs derived root')).toBeInTheDocument()
  expect(screen.getByText('Adds: 1 task · 1 command')).toBeInTheDocument()
  expect(screen.getByText(/ALLOWED_DERIVED_ROOTS/)).toBeInTheDocument()
})
