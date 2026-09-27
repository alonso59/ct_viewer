// PHS-01/03/07 UI half on the mock API: one click sets the scan's phase at once, the replaced
// value stays visible ("was …"), and the history lists the selection.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useReviewer } from '../../state'
import { PhaseButtons, PhaseHistoryButton } from './PhaseButtons'

test('a click sets the phase at once, keeps the replaced value, and shows in the history', async () => {
  useReviewer.setState({ name: 'Dr. P' })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const before = (await api.getCase(DEMO_PID, 'case_00001')).items.find((i) => i.scope === 'complete')!
  const next = before.phase.canonical === 'EP' ? 'NC' : 'EP'
  render(
    <QueryClientProvider client={qc}>
      <PhaseButtons pid={DEMO_PID} scan={before} />
      <PhaseHistoryButton pid={DEMO_PID} caseId={before.case_id} scanIdx={before.scan_idx} />
    </QueryClientProvider>,
  )
  const group = await screen.findByRole('group', { name: `Phase of ${before.case_id} · ${before.scan_idx}` })
  await waitFor(() => expect(within(group).getAllByRole('button').length).toBeGreaterThan(3)) // the project vocabulary
  fireEvent.click(within(group).getByRole('button', { name: next }))
  await waitFor(async () => {
    const it = (await api.getCase(DEMO_PID, 'case_00001')).items.find((i) => i.item_id === before.item_id)!
    expect(it.phase).toMatchObject({ canonical: next, source: 'manual', resolved: { canonical: before.phase.canonical } })
  })
  fireEvent.click(screen.getByRole('button', { name: 'Phase history' }))
  const dlg = await screen.findByRole('dialog')
  expect(await within(dlg).findByText('Selected')).toBeInTheDocument()
  expect(within(dlg).getByText(/Dr\. P/)).toBeInTheDocument()
})

// PHS-01 / AUD-A1-12: in the case header the scan's phase is a segmented control with the effective
// value pressed, apart from the scan chips of the item switcher
test('the case header variant is a segmented control with the effective phase pressed', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const scan = (await api.getCase(DEMO_PID, 'case_00001')).items.find((i) => i.scope === 'complete')!
  const { container } = render(
    <QueryClientProvider client={qc}>
      <PhaseButtons pid={DEMO_PID} scan={scan} variant="seg" />
    </QueryClientProvider>,
  )
  const group = await screen.findByRole('group', { name: `Phase of ${scan.case_id} · ${scan.scan_idx}` })
  await waitFor(() => expect(within(group).getAllByRole('button').length).toBeGreaterThan(3))
  expect(container.querySelector('.seg')).not.toBeNull()
  expect(within(group).getByRole('button', { name: scan.phase.canonical })).toHaveAttribute('aria-pressed', 'true')
  expect(within(group).getAllByRole('button').filter((b) => b.getAttribute('aria-pressed') === 'true')).toHaveLength(1)
})
