// @vitest-environment jsdom
// COH-04: a grid cell's menu copies the value, filters by it, and opens the item in the viewer;
// the queue action is only offered where the workbench may write.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { useMemo } from 'react'
import { vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { keys, type CohortCaseRow, type Project, type Variable, type VariableCategory, type VariableOrigin } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { registry, useWorkbench } from '../../shell'
import { CohortEditor } from './CohortEditor'
import { useCellMenu } from './CellMenu'
import { EMPTY_FILTERS, useCohort } from './store'

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => useMemo(() => ({
    measure: () => {},
    scrollToIndex: () => {},
    getTotalSize: () => count * 22,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, key: index, size: 22, start: index * 22 })),
  }), [count]),
}))

const v = (name: string, origin: VariableOrigin, category: VariableCategory | null): Variable => ({
  name, source: 'metadata', type: 'categorical', inferred_type: 'categorical', level: 'case', group: 'study', origin, category,
  tags: [], visible: true, confidence: 1, review: false, overridden: false, comparable: false,
  profile: { missing_pct: 0, n_distinct: 2, examples: [], levels: [{ value: 'B', count: 5 }, { value: 'A', count: 3 }] },
})

const CATALOG: Variable[] = [
  v('manufacturer', 'metadata', 'equipment'),
  v('manufacturer_model', 'metadata', 'equipment'),
]

const COLUMNS = ['manufacturer', 'manufacturer_model']
const B0 = { columns: COLUMNS, filters: {}, sort: null, offset: 0, limit: 100 }
const BVAR = { columns: COLUMNS, filters: { 'manufacturer': ['Siemens'] }, sort: null, offset: 0, limit: 100 }

const ROWS: CohortCaseRow[] = [
  {
    case_id: 'case-1',
    values: { manufacturer: 'Siemens', manufacturer_model: 'Vida 64' },
    scans: [
      { scan_idx: 's1', item_id: 'item-1', phase: 'NC', modality: 'CT', values: { manufacturer: 'Siemens', manufacturer_model: 'Vida 64' } },
    ],
  },
  {
    case_id: 'case-2',
    values: { manufacturer: 'GE', manufacturer_model: '750' },
    scans: [
      { scan_idx: 's1', item_id: 'item-3', phase: 'NC', modality: 'CT', values: { manufacturer: 'GE', manufacturer_model: '750' } },
    ],
  },
]

function renderGrid() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.project(DEMO_PID), { project_id: DEMO_PID, phase_vocabulary: ['NC'], default_seg: 'imported' } as unknown as Project)
  qc.setQueryData(keys.variables(DEMO_PID), CATALOG)
  qc.setQueryData(keys.curationState(DEMO_PID), [])
  qc.setQueryData(keys.cohortRows(DEMO_PID, B0), { n_cases: 2, n_scans: 2, rows: ROWS })
  qc.setQueryData(keys.cohortRows(DEMO_PID, BVAR), { n_cases: 1, n_scans: 1, rows: [ROWS[0]!] })
  return render(
    <QueryClientProvider client={qc}>
      <CohortEditor />
    </QueryClientProvider>,
  )
}

// The first variable cell of the first case row
const contextMenuCell = () => {
  const cell = document.querySelector('.cohort-row-case .cohort-cell')
  expect(cell).not.toBeNull()
  fireEvent.contextMenu(cell as HTMLElement, { clientX: 12, clientY: 34 })
}

beforeEach(() => {
  useWorkbench.setState({ pid: DEMO_PID })
  useCohort.setState({ pid: null, byProject: {}, group: null, pinned: [], expanded: {}, filters: EMPTY_FILTERS })
  useCohort.getState().openProject(DEMO_PID)
  useCohort.getState().setGroup({ origin: 'metadata', category: 'equipment' })
  useCellMenu.setState({ target: null })
  registry.setReadOnly(false)
})

afterEach(() => {
  registry.setReadOnly(false)
})

test('a cell menu offers copy, filter, open and queue', () => {
  renderGrid()
  contextMenuCell()
  expect(screen.getByRole('menuitem', { name: 'Copy value' })).toBeInTheDocument()
  expect(screen.getByRole('menuitem', { name: 'Filter by this value' })).toBeInTheDocument()
  expect(screen.getByRole('menuitem', { name: 'Open in viewer' })).toBeInTheDocument()
  expect(screen.getByRole('menuitem', { name: 'Add to correction queue' })).toBeInTheDocument()
})

test('filter by this value adds the variable chip and narrows the grid', () => {
  renderGrid()
  contextMenuCell()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Filter by this value' }))
  expect(useCohort.getState().filters.vars).toEqual({ manufacturer: ['Siemens'] })
  expect(screen.getByText('manufacturer: Siemens')).toBeInTheDocument()
  expect(Array.from(document.querySelectorAll('.cohort-row-case .cohort-cell-id')).map((el) => el.textContent)).toEqual(['case-1'])
})

test('a view-only workbench hides the queue action', () => {
  renderGrid()
  registry.setReadOnly(true)
  contextMenuCell()
  expect(screen.queryByRole('menuitem', { name: 'Add to correction queue' })).not.toBeInTheDocument()
  expect(screen.getByRole('menuitem', { name: 'Open in viewer' })).toBeInTheDocument()
})
