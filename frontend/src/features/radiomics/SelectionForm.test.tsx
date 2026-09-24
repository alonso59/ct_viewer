// RAD-05 "Use the current Explorer filter": the Explorer filter maps onto the run selection;
// criteria API-33/34 cannot take are listed as not sent.
import * as RTooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { DEMO_PID } from '../../api/mock/server'
import { useExplorer } from '../explorer/store'
import { emptySelection, type SelectionForm as Sel } from './model/selection'
import { SelectionForm } from './SelectionForm'

function setup() {
  const onChange = vi.fn<(p: Partial<Sel>) => void>()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RTooltip.Provider>
        <SelectionForm pid={DEMO_PID} sel={emptySelection([1])} onChange={onChange} issues={[]} />
      </RTooltip.Provider>
    </QueryClientProvider>,
  )
  return onChange
}
const button = () => screen.getByRole('button', { name: 'Use the current Explorer filter' })

afterEach(() => act(() => useExplorer.getState().clearFilter()))

test('disabled while the Explorer has no filter', () => {
  setup()
  expect(button()).toBeDisabled()
})

test('phase + level filters become filter mode; ranges and case-only criteria are reported', () => {
  act(() => useExplorer.setState({ filter: { phase: 'NP', status: 'accepted', vars: { sex: 'F', hb: '10..50' } } }))
  const onChange = setup()
  fireEvent.click(button())
  expect(onChange).toHaveBeenCalledWith({ mode: 'filter', phase: ['NP'], side: [], vars: { sex: ['F'] } })
  expect(screen.getByText('Explorer filter applied.')).toBeInTheDocument()
  expect(screen.getByText('Not sent: the curation status filter.')).toBeInTheDocument()
  expect(screen.getByText(/Not sent: ranges on hb\./)).toBeInTheDocument()
})

test('a dashboard item list becomes list mode with its shared scope', () => {
  act(() => useExplorer.getState().setItemIds(['case_00001.01.voi.L', 'case_00002.01.voi.R']))
  const onChange = setup()
  fireEvent.click(button())
  expect(onChange).toHaveBeenCalledWith({ mode: 'list', list: 'case_00001.01.voi.L\ncase_00002.01.voi.R', scope: 'voi' })
  expect(screen.getByText('Explorer item list applied (2 items).')).toBeInTheDocument()
})
