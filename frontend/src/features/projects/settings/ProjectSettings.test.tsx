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

function renderSettings(tab?: 'general' | 'plugins') {
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
