// @vitest-environment jsdom
// DB-11: a view with a chart shows its rows as a table on request; a row of an item has a checkbox
// for the linked selection (DB-04), the keyboard alternative to brushing.
import { fireEvent, render, screen, within } from '@testing-library/react'

import '../../../i18n'
import '../../../i18n/lazy'
import { useDashboardStore } from '../store'
import { ChartOrTable, ViewFrame } from './common'

const ITEM = 'case_00001.01.complete.-'

test('Show as table swaps the chart for its rows; an item row selects like a brush', () => {
  render(
    <ViewFrame name="view" chart={null} csv={() => [['item_id', 'case_id', 'volume'], [ITEM, 'case_00001', 1.5]]}>
      <ChartOrTable runId="run-1">
        <div data-testid="chart" />
      </ChartOrTable>
    </ViewFrame>,
  )
  const toggle = screen.getByRole('button', { name: 'Show as table' })
  expect(toggle).toHaveAttribute('aria-pressed', 'false')
  expect(screen.getByTestId('chart')).toBeInTheDocument()
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-pressed', 'true')
  expect(screen.queryByTestId('chart')).toBeNull()
  const table = screen.getByRole('region', { name: 'Chart values' })
  expect(within(table).getByRole('columnheader', { name: 'volume' })).toBeInTheDocument()
  expect(within(table).getByText('1.5')).toBeInTheDocument()
  fireEvent.click(within(table).getByRole('checkbox', { name: `Select ${ITEM}` }))
  expect(useDashboardStore.getState().runs['run-1']?.selection).toEqual([ITEM])
  fireEvent.click(toggle)
  expect(screen.getByTestId('chart')).toBeInTheDocument()
})

test('a view without a chart has no table switch', () => {
  render(<ViewFrame name="view" csv={() => [['feature'], ['a']]}><span /></ViewFrame>)
  expect(screen.queryByRole('button', { name: 'Show as table' })).toBeNull()
})
