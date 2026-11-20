// @vitest-environment jsdom
// ADR-0060: the Dashboards view lists the finished analysis tables by kind.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'

import '../../i18n'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { DashboardsView } from './DashboardsView'

test('lists radiomics runs and VOI lesions tables in their own groups', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <DashboardsView />
    </QueryClientProvider>,
  )
  const lesions = await screen.findByRole('region', { name: 'VOI lesions' })
  expect(within(lesions).getByRole('button', { name: /VOI lesions/ })).toHaveTextContent(/3 × lesion · 3 items/)
  const radiomics = screen.getByRole('region', { name: 'Radiomics' })
  expect(within(radiomics).getByRole('button', { name: /NP tumor first-order/ })).toBeInTheDocument()
})
