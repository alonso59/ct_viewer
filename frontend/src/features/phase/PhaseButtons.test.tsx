// @vitest-environment jsdom
// PHS-01/03/07 UI half on the recorded API (TST-04): a click sends one selection at once; a scan
// with a selection shows the replaced value ("was …"), and the history lists the selection. What
// the server makes of it (precedence, PHS-03) is backend/tests/test_phase.py.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useReviewer } from '../../state'
import { PhaseButtons, PhaseHistoryButton } from './PhaseButtons'

afterEach(() => vi.restoreAllMocks())

test('a click sends the selection at once; the replaced value and the history show', async () => {
  useReviewer.setState({ name: 'Dr. P' })
  const append = vi.spyOn(api, 'appendPhase')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // the recording selected NP on case_00002 scan 02, indexed as CMP
  const scan = (await api.getCase(DEMO_PID, 'case_00002')).items.find((i) => i.scan_idx === '02' && i.scope === 'complete')!
  expect(scan.phase).toMatchObject({ canonical: 'NP', source: 'manual', resolved: { canonical: 'CMP' } })
  render(
    <QueryClientProvider client={qc}>
      <PhaseButtons pid={DEMO_PID} scan={scan} />
      <PhaseHistoryButton pid={DEMO_PID} caseId={scan.case_id} scanIdx={scan.scan_idx} />
    </QueryClientProvider>,
  )
  const group = await screen.findByRole('group', { name: `Phase of ${scan.case_id} · ${scan.scan_idx}` })
  await waitFor(() => expect(within(group).getAllByRole('button').length).toBeGreaterThan(3)) // the project vocabulary
  expect(within(group).getByText('was CMP')).toBeInTheDocument()
  fireEvent.click(within(group).getByRole('button', { name: 'EP' }))
  await waitFor(() => expect(append).toHaveBeenCalledWith(DEMO_PID, { case_id: 'case_00002', scan_idx: '02', value: 'EP', source: 'manual' }, 'Dr. P'))
  fireEvent.click(screen.getByRole('button', { name: 'Phase history' }))
  const dlg = await screen.findByRole('dialog')
  expect(await within(dlg).findByText('Selected')).toBeInTheDocument()
  expect(within(dlg).getByText(/Dr\. AP/)).toBeInTheDocument()
})

test('the history dialog says it is loading and offers Try again when the load fails', async () => {
  const events = vi.spyOn(api, 'phaseEvents').mockRejectedValueOnce(new Error('boom'))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><PhaseHistoryButton pid={DEMO_PID} caseId="case_00002" scanIdx="02" /></QueryClientProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Phase history' }))
  const dlg = await screen.findByRole('dialog')
  expect(within(dlg).getByText('Loading…')).toBeInTheDocument()
  fireEvent.click(await within(dlg).findByRole('button', { name: 'Try again' }))
  expect(await within(dlg).findByText('Selected')).toBeInTheDocument()
  expect(events).toHaveBeenCalledTimes(2)
})

// PHS-01 (AUD-A1-12): the case header's phase is a write, so it uses chips with the effective
// value pressed, never the segmented style of the view toggles beside it
test('the case header writes the phase with chips, the effective one pressed', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const scan = (await api.getCase(DEMO_PID, 'case_00001')).items.find((i) => i.scope === 'complete')!
  const { container } = render(
    <QueryClientProvider client={qc}>
      <PhaseButtons pid={DEMO_PID} scan={scan} />
    </QueryClientProvider>,
  )
  const group = await screen.findByRole('group', { name: `Phase of ${scan.case_id} · ${scan.scan_idx}` })
  await waitFor(() => expect(within(group).getAllByRole('button').length).toBeGreaterThan(3))
  expect(container.querySelector('.seg')).toBeNull()
  expect(within(group).getByRole('button', { name: scan.phase.canonical })).toHaveClass('badge')
  expect(within(group).getByRole('button', { name: scan.phase.canonical })).toHaveAttribute('aria-pressed', 'true')
  expect(within(group).getAllByRole('button').filter((b) => b.getAttribute('aria-pressed') === 'true')).toHaveLength(1)
})
