// UI-23 / PRJ-15/16/17 on the mock API: tabs, If-Match conflict → reload and reapply, packs, view link.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../../i18n'
import '../../../i18n/lazy'
import { api } from '../../../api'
import { DEMO_PID } from '../../../api/mock/server'
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

test('a stale save shows the conflict; reload and reapply saves on the fresh version', async () => {
  renderSettings()
  const name = await screen.findByDisplayValue('Dataset900 (synthetic)')
  fireEvent.change(name, { target: { value: 'Renamed here' } })
  // Someone else changes the settings in between (new ETag on the server)
  const other = await api.getProject(DEMO_PID)
  await api.updateProject(DEMO_PID, { description: 'by someone else' }, other.etag)
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText(/changed by someone else/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Reload and reapply' }))
  await waitFor(async () => expect((await api.getProject(DEMO_PID)).name).toBe('Renamed here'))
  expect((await api.getProject(DEMO_PID)).description).toBe('by someone else')
})

test('all five tabs; the Plugins tab applies a pack; General creates a view-only link', async () => {
  renderSettings('plugins')
  for (const tab of ['General', 'Display', 'Labels', 'Data', 'Plugins']) expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument()
  const row = await screen.findByText('Generic CT phases')
  const li = row.closest('li') as HTMLElement
  fireEvent.click(within(li).getByRole('button', { name: 'Apply' }))
  await waitFor(async () => expect((await api.getProject(DEMO_PID)).packs).toContain('generic-ct'))
  fireEvent.click(screen.getByRole('tab', { name: 'General' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Create view-only link' }))
  await waitFor(async () => expect((await api.getProject(DEMO_PID)).view_url).toMatch(/\/v\//))
})
