// DB-04: the item-id filter narrows the Project view to the items' cases; the chip clears it.
import * as RTooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import '../../i18n'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { ProjectView } from './ProjectView'
import { useExplorer } from './store'

test('item filter: "N items" chip, only their cases, clearable', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  useExplorer.getState().clearFilter()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RTooltip.Provider>
        <ProjectView />
      </RTooltip.Provider>
    </QueryClientProvider>,
  )
  const count = () => Number(/^(\d+) cases?$/.exec(screen.getByText(/^\d+ cases?$/).textContent ?? '')?.[1])
  await waitFor(() => expect(count()).toBeGreaterThan(2), { timeout: 3_000 })
  const total = count()

  act(() => useExplorer.getState().setItemIds(['case_00001.01.complete.-', 'case_00002.01.complete.-', 'case_00002.02.complete.-']))
  expect(await screen.findByText('3 items')).toBeInTheDocument()
  expect(await screen.findByText('2 cases', {}, { timeout: 3_000 })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Clear the item filter' }))
  expect(screen.queryByText('3 items')).not.toBeInTheDocument()
  expect(await screen.findByText(`${total} cases`, {}, { timeout: 3_000 })).toBeInTheDocument()
})
