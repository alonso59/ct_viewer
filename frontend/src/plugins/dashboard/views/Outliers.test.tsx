// @vitest-environment jsdom
// DB-10 (owner 2026-09-27): the Outliers view asks for flagged items with the threshold and the
// minimum share of features (default 3.5 and 5 %), both adjustable; it lists what the server
// flagged, in the server's order (AUD-A2-06), and "Show all" asks for every flagged item.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import '../../../i18n'
import '../../../i18n/lazy'
import { api } from '../../../api'
import { DEMO_PID } from '../../../api/mock/server'
import { useWorkbench } from '../../../shell'
import { OUTLIERS_MIN_PCT, OUTLIERS_THRESHOLD, OUTLIERS_TOP, OutliersView } from './Outliers'

afterEach(() => vi.restoreAllMocks())

const item = (i: number, n: number) => ({
  item_id: `case_${String(i).padStart(5, '0')}.01.complete.-`,
  case_id: `case_${String(i).padStart(5, '0')}`,
  label: 2,
  status: 'not_reviewed',
  max_abs_z: 10 - i / 10,
  n_outlier_features: n,
  top_features: [{ feature: 'original_firstorder_Mean', value: 1.5, z: 9 }],
})

test('sends the threshold and the minimum share, and lists the flagged items (DB-10)', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  const flagged = Array.from({ length: 12 }, (_, i) => item(i + 1, 12 - i))
  const view = vi.spyOn(api, 'dashboardView').mockImplementation(async (_pid, _rid, _v, body) => {
    const b = body as { top_n: number; min_feature_pct: number; threshold: number }
    return { threshold: b.threshold, min_feature_pct: b.min_feature_pct, min_features: 1, n_features: 13, n_items: 40, n_flagged: flagged.length, items: flagged.slice(0, b.top_n), features: [] } as never
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <OutliersView runId="r1" />
    </QueryClientProvider>,
  )
  await waitFor(() => expect(view).toHaveBeenCalledWith(DEMO_PID, 'r1', 'outliers', expect.objectContaining({ threshold: OUTLIERS_THRESHOLD, min_feature_pct: OUTLIERS_MIN_PCT, top_n: OUTLIERS_TOP })))
  const table = await screen.findByRole('table', { name: 'Outliers' })
  await waitFor(() => expect(table.querySelectorAll('tbody tr')).toHaveLength(OUTLIERS_TOP))
  expect(screen.getByTestId('outliers-flagged')).toHaveTextContent('12 of 40 items flagged')

  fireEvent.change(screen.getByRole('spinbutton', { name: /Min\. features/ }), { target: { value: '20' } })
  await waitFor(() => expect(view).toHaveBeenCalledWith(DEMO_PID, 'r1', 'outliers', expect.objectContaining({ min_feature_pct: 20, top_n: OUTLIERS_TOP })))
  fireEvent.change(screen.getByRole('spinbutton', { name: /\|z\|/ }), { target: { value: '2,5' } })
  await waitFor(() => expect(view).toHaveBeenCalledWith(DEMO_PID, 'r1', 'outliers', expect.objectContaining({ threshold: 2.5, min_feature_pct: 20 })))

  fireEvent.click(screen.getByRole('button', { name: 'Show all 12' }))
  await waitFor(() => expect(view).toHaveBeenCalledWith(DEMO_PID, 'r1', 'outliers', expect.objectContaining({ top_n: 12, min_feature_pct: 20 })))
  await waitFor(() => expect(table.querySelectorAll('tbody tr')).toHaveLength(12))
})
