// @vitest-environment jsdom
// ADR-0061: a `voi.extract` run's lesions and training profile, read from the recorded run.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import ProfilePanel, { VolumeHistogram } from './Profile'

afterEach(() => vi.restoreAllMocks())

async function recordedRun(): Promise<string> {
  const tables = await api.listTables(DEMO_PID)
  const lesions = tables.find((t) => t.kind === 'voi_lesions')
  if (!lesions) throw new Error('the recording has no VOI lesions table')
  return lesions.producer.run_id
}

function renderPanel(runId: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ProfilePanel pid={DEMO_PID} runId={runId} settings={{ bin_percentiles: [50] }} />
    </QueryClientProvider>,
  )
}

test('shows the size bins, their sampling and the saved variants of the run', async () => {
  const runId = await recordedRun()
  renderPanel(runId)
  const table = await screen.findByRole('table')
  await waitFor(() => expect(table.querySelectorAll('tbody tr')).toHaveLength(2))
  expect(table).toHaveTextContent('b0')
  expect(table).toHaveTextContent('≤ 0.415 mL')
  expect(screen.getByRole('img', { name: /3 lesions on a log scale/ })).toBeInTheDocument()
  expect(await screen.findByRole('link', { name: 'balanced' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /sampling_profile.json of the run/ })).toBeInTheDocument()
})

test('an edit recomputes the profile with the run settings changed', async () => {
  const runId = await recordedRun()
  const profile = vi.spyOn(api, 'voiProfile')
  renderPanel(runId)
  await screen.findByRole('table')
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Balancing' }), { target: { value: '1' } })
  await waitFor(() => expect(profile).toHaveBeenLastCalledWith(DEMO_PID, runId, { balancing_alpha: 1 }))
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Patches per lesion in b1' }), { target: { value: '7' } })
  await waitFor(() => expect(profile).toHaveBeenLastCalledWith(DEMO_PID, runId, expect.objectContaining({ budget_by_bin: [expect.any(Number), 7] })))
  expect(screen.getByRole('button', { name: 'Save variant' })).toBeDisabled()
  fireEvent.change(screen.getByRole('textbox', { name: 'Variant name' }), { target: { value: 'run' } })
  expect(screen.getByRole('button', { name: 'Save variant' })).toBeDisabled()
  fireEvent.change(screen.getByRole('textbox', { name: 'Variant name' }), { target: { value: 'wide_context' } })
  expect(screen.getByRole('button', { name: 'Save variant' })).toBeEnabled()
})

test('the histogram draws the cuts inside the volume range', () => {
  const { container } = render(<VolumeHistogram volumesMm3={[100, 1000, 10_000, 100_000]} cutsMm3={[5000]} />)
  expect(container.querySelectorAll('.voi-hist-bar').length).toBeGreaterThan(0)
  const cut = container.querySelector('.voi-hist-cut')
  expect(Number(cut?.getAttribute('x1'))).toBeGreaterThan(0)
  expect(render(<VolumeHistogram volumesMm3={[]} cutsMm3={[]} />).container.innerHTML).toBe('')
})
