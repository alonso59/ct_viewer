// @vitest-environment jsdom
// COH-03 / COH-10: the grid lists the cases with the open group's fields, expands a case to its
// scans, marks values that differ across the scans, and orders the rows from the headers.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { useMemo } from 'react'
import { vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { keys, type CohortCaseRow, type Variable, type VariableCategory, type VariableOrigin } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { CohortEditor } from './CohortEditor'
import { useCohort } from './store'

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => useMemo(() => ({
    measure: () => {},
    scrollToIndex: () => {},
    getTotalSize: () => count * 22,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, key: index, size: 22, start: index * 22 })),
  }), [count]),
}))

const v = (name: string, origin: VariableOrigin, category: VariableCategory | null, extra: Partial<Variable> = {}): Variable => ({
  name, source: 'metadata', type: 'categorical', inferred_type: 'categorical', level: 'case', group: 'study', origin, category,
  tags: [], visible: true, confidence: 1, review: false, overridden: false, comparable: false,
  profile: { missing_pct: 0, n_distinct: 2, examples: [], levels: [{ value: 'B', count: 5 }, { value: 'A', count: 3 }] },
  ...extra,
})

const CATALOG: Variable[] = [
  v('manufacturer', 'metadata', 'equipment'),
  v('manufacturer_model', 'metadata', 'equipment'),
]

const COLUMNS = ['manufacturer', 'manufacturer_model']
const BODY = { columns: COLUMNS, filters: {}, sort: null, offset: 0, limit: 100 }
const SORTED = { columns: COLUMNS, filters: {}, sort: { column: 'manufacturer', desc: false }, offset: 0, limit: 100 }
const SORTED_DESC = { columns: COLUMNS, filters: {}, sort: { column: 'manufacturer', desc: true }, offset: 0, limit: 100 }

const ROWS: CohortCaseRow[] = [
  {
    case_id: 'case-1',
    values: { manufacturer: 'Siemens', manufacturer_model: null },
    differs: ['manufacturer_model'],
    scans: [
      { scan_idx: 's1', item_id: 'item-1', phase: 'nc', modality: 'CT', values: { manufacturer: 'Siemens', manufacturer_model: 'Vida 64' } },
      { scan_idx: 's2', item_id: 'item-2', phase: 'a', modality: 'CT', values: { manufacturer: 'Siemens', manufacturer_model: 'Vida 64b' } },
    ],
  },
  {
    case_id: 'case-2',
    values: { manufacturer: 'GE', manufacturer_model: '750' },
    scans: [
      { scan_idx: 's1', item_id: 'item-3', phase: 'nc', modality: 'CT', values: { manufacturer: 'GE', manufacturer_model: '750' } },
    ],
  },
]

function renderGrid() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(keys.variables(DEMO_PID), CATALOG)
  qc.setQueryData(keys.cohortRows(DEMO_PID, { ...BODY, columns: [] }), { n_cases: 2, n_scans: 3, rows: ROWS })
  qc.setQueryData(keys.cohortRows(DEMO_PID, BODY), { n_cases: 2, n_scans: 3, rows: ROWS })
  qc.setQueryData(keys.cohortRows(DEMO_PID, SORTED), { n_cases: 2, n_scans: 3, rows: [ROWS[1]!, ROWS[0]!] })
  qc.setQueryData(keys.cohortRows(DEMO_PID, SORTED_DESC), { n_cases: 2, n_scans: 3, rows: ROWS })
  return render(
    <QueryClientProvider client={qc}>
      <CohortEditor />
    </QueryClientProvider>,
  )
}

/** The case row's outer element: the one carrying aria-expanded */
const caseRow = (cid: string) => screen.getByText(cid).closest('[aria-expanded]') as HTMLElement
const caseIds = () => Array.from(document.querySelectorAll('.cohort-row-case .cohort-cell-id')).map((el) => el.textContent)

beforeEach(() => {
  useWorkbench.setState({ pid: DEMO_PID })
  useCohort.setState({ pid: null, byProject: {}, group: null, pinned: [], expanded: {} })
  useCohort.getState().openProject(DEMO_PID)
  useCohort.getState().setGroup({ origin: 'metadata', category: 'equipment' })
})

test('with no group chosen the cases still show, and the Cohort navigator opens beside them', () => {
  useLayout.setState({ activeView: 'project', sidebarVisible: false })
  renderGrid()
  act(() => useCohort.getState().setGroup(null))
  expect(screen.getByText('case-1')).toBeInTheDocument()
  expect(screen.getByText(/Pick a group in the navigator/)).toBeInTheDocument()
  expect(useLayout.getState().activeView).toBe('cohort')
  expect(useLayout.getState().sidebarVisible).toBe(true)
})

test('a case row expands to its scans and collapses again', () => {
  renderGrid()
  const row1 = caseRow('case-1')
  expect(row1.getAttribute('aria-expanded')).toBe('false')
  fireEvent.click(row1)
  expect(row1.getAttribute('aria-expanded')).toBe('true')
  expect(useCohort.getState().expanded['case-1']).toBe(true)
  expect(screen.getByText('Vida 64')).toBeInTheDocument()
  expect(screen.getByText('s2')).toBeInTheDocument()
  fireEvent.click(row1)
  expect(row1.getAttribute('aria-expanded')).toBe('false')
  expect(screen.queryByText('Vida 64')).not.toBeInTheDocument()
})

test('a value that differs across the scans is marked with its count in words', () => {
  renderGrid()
  const row1 = caseRow('case-1')
  expect(within(row1).getByText('2 values')).toBeInTheDocument()
  expect(row1.querySelector('.codicon-diff')).not.toBeNull()
  // The common value still shows; the uniform case shows its plain value
  expect(within(row1).getByText('Siemens')).toBeInTheDocument()
  expect(within(caseRow('case-2')).getByText('750')).toBeInTheDocument()
})

test('one tab stop: arrows move between rows, Enter toggles the case', () => {
  renderGrid()
  const row1 = caseRow('case-1')
  const row2 = caseRow('case-2')
  expect(row1.tabIndex).toBe(0)
  fireEvent.focus(row1)
  fireEvent.keyDown(row1, { key: 'ArrowDown' })
  expect(document.activeElement).toBe(row2)
  fireEvent.keyDown(row2, { key: 'ArrowUp' })
  expect(document.activeElement).toBe(row1)
  fireEvent.keyDown(row1, { key: 'Enter' })
  expect(row1.getAttribute('aria-expanded')).toBe('true')
  // The expanded case's scans join the keyboard path
  fireEvent.keyDown(row1, { key: 'ArrowDown' })
  expect(document.activeElement).toBe(screen.getByText('Vida 64').closest('[tabindex]'))
})

test('a header click sorts the rows; a single page disables paging', () => {
  renderGrid()
  expect(caseIds()).toEqual(['case-1', 'case-2'])
  expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  const head = screen.getByRole('columnheader', { name: 'manufacturer' })
  fireEvent.click(head)
  expect(head.getAttribute('aria-sort')).toBe('ascending')
  expect(caseIds()).toEqual(['case-2', 'case-1'])
  fireEvent.click(head)
  expect(head.getAttribute('aria-sort')).toBe('descending')
  expect(caseIds()).toEqual(['case-1', 'case-2'])
})
