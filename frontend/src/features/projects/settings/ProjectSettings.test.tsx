// @vitest-environment jsdom
// UI-23 / PRJ-15/16/17 on the recorded API (TST-04): tabs, If-Match conflict (the recorded 412) →
// reload and reapply, packs, view link. The writes are asserted as sent; their effect is the backend's.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../../i18n'
import '../../../i18n/lazy'
import { api } from '../../../api'
import { DEMO_PID } from '../../../api/mock/server'
import { recordedProblem } from '../../../test/recorded'
import { useWorkbench } from '../../../shell'
import ProjectSettings from './ProjectSettings'

function renderSettings(tab?: 'general' | 'plugins' | 'labels') {
  useWorkbench.setState({ pid: DEMO_PID })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ProjectSettings params={{ tab }} panelId="settings" active />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

test('a stale save shows the conflict; reload and reapply saves on the fresh version', async () => {
  const project = await api.getProject(DEMO_PID)
  const update = vi.spyOn(api, 'updateProject').mockRejectedValueOnce(recordedProblem('PATCH', `/api/v1/projects/${DEMO_PID}`, { description: 'stale' }))
  renderSettings()
  const name = await screen.findByDisplayValue('Dataset900 (synthetic)')
  fireEvent.change(name, { target: { value: 'Renamed here' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText(/changed by someone else/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Reload and reapply' }))
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
  const [, patch, etag] = update.mock.calls[1]!
  expect(patch).toMatchObject({ name: 'Renamed here' })
  expect(patch).not.toHaveProperty('description') // only the edited field goes: the other edit stays
  expect(etag).toBe(project.etag)
})

test('all five tabs; the Plugins tab applies a pack; General creates a view-only link', async () => {
  const apply = vi.spyOn(api, 'applyPack')
  const token = vi.spyOn(api, 'createViewToken')
  renderSettings('plugins')
  for (const tab of ['General', 'Display', 'Labels', 'Data', 'Plugins']) expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument()
  const row = await screen.findByText('Generic CT phases')
  const li = row.closest('li') as HTMLElement
  fireEvent.click(within(li).getByRole('button', { name: 'Apply' }))
  await waitFor(() => expect(apply).toHaveBeenCalledWith(DEMO_PID, 'generic-ct'))
  fireEvent.click(screen.getByRole('tab', { name: 'General' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Create view-only link' }))
  await waitFor(() => expect(token).toHaveBeenCalledWith(DEMO_PID))
  expect((await token.mock.results[0]!.value) as { view_url: string }).toMatchObject({ view_url: expect.stringMatching(/\/v\//) })
})

test('catalog removal is a draft, can be discarded and saves only label metadata', async () => {
  const project = await api.getProject(DEMO_PID)
  const update = vi.spyOn(api, 'updateProject')
  const first = project.label_map[0]!
  renderSettings('labels')
  const removeName = `Remove label ${first.name} from the catalog`
  fireEvent.click(await screen.findByRole('button', { name: removeName }))
  expect(screen.queryByRole('button', { name: removeName })).not.toBeInTheDocument()
  expect(update).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Discard my changes' }))
  fireEvent.click(await screen.findByRole('button', { name: removeName }))
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
  expect(update.mock.calls[0]![1]).toEqual({ label_map: project.label_map.slice(1) })
  expect(update.mock.calls[0]![2]).toBe(project.etag)
})

test('catalog import previews replacement and allows choosing the same file again', async () => {
  const update = vi.spyOn(api, 'updateProject')
  renderSettings('labels')
  const input = await screen.findByLabelText('Import label file…')
  fireEvent.change(screen.getByRole('combobox', { name: 'Label import mode' }), { target: { value: 'replace' } })
  const catalog = [{ value: 17, name: 'Reviewed structure', color: '#123456', opacity: 0.4, visible: false }]
  const file = new File([JSON.stringify({ label_map: catalog })], 'catalog.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => JSON.stringify({ label_map: catalog }) })
  fireEvent.change(input, { target: { files: [file] } })
  await screen.findByDisplayValue('Reviewed structure')
  expect(screen.getAllByRole('button', { name: /Remove label .* from the catalog/ })).toHaveLength(1)
  expect(update).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Remove label Reviewed structure from the catalog' }))
  fireEvent.change(input, { target: { files: [file] } })
  await screen.findByDisplayValue('Reviewed structure')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
  expect(update.mock.calls[0]![1]).toEqual({ label_map: catalog })
})
