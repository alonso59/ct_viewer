// @vitest-environment jsdom
// COH-05: the grid's filters show as removable chips, narrow the rows server-side, persist per
// project, and send to the Explorer.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { useMemo } from 'react'
import { vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { keys, type CohortCaseRow, type Project, type Variable, type VariableCategory, type VariableOrigin } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { useExplorer } from '../explorer/store'
import { CohortEditor } from './CohortEditor'
import { EMPTY_FILTERS, useCohort } from './store'

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
// The request body in the query key; the fields match the editor's order
const B0 = { columns: COLUMNS, filters: {}, sort: null, offset: 0, limit: 100 }
const BVAR = { columns: COLUMNS, filters: { 'manufacturer': ['SIEMENS'] }, sort: null, offset: 0, limit: 100 }
const BPHASE = { columns: COLUMNS, filters: {}, phase: 'NC', sort: null, offset: 0, limit: 100 }
const BQ = { columns: COLUMNS, filters: {}, q: 'case_', sort: null, offset: 0, limit: 100 }
const BQPHASE = { columns: COLUMNS, filters: {}, q: 'case_', phase: 'NC', sort: null, offset: 0, limit: 100 }
const BVARPHASE = { columns: COLUMNS, filters: { 'manufacturer': ['SIEMENS'] }, phase: 'NC', sort: null, offset: 0, limit: 100 }
const BSEND = {
  columns: COLUMNS,
  filters: { 'manufacturer': ['SIEMENS'], 'manufacturer_model': ['Vida 64', 'Vida 64b'] },
  q: 'case_',
  phase: 'NC',
  sort: null,
  offset: 0,
  limit: 100,
}

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
  qc.setQueryData(keys.project(DEMO_PID), { project_id: DEMO_PID, phase_vocabulary: ['NC', 'CMP', 'NP', 'EP'] } as unknown as Project)
  qc.setQueryData(keys.variables(DEMO_PID), CATALOG)
  // The persistence test switches projects; keep its fetches out of the assertions
  qc.setQueryData(keys.project('other'), { project_id: 'other', phase_vocabulary: [] } as unknown as Project)
  qc.setQueryData(keys.variables('other'), [])
  const one = { n_cases: 1, n_scans: 1, rows: [ROWS[0]!] }
  qc.setQueryData(keys.cohortRows(DEMO_PID, B0), { n_cases: 2, n_scans: 2, rows: ROWS })
  qc.setQueryData(keys.cohortRows(DEMO_PID, BVAR), one)
  qc.setQueryData(keys.cohortRows(DEMO_PID, BPHASE), one)
  qc.setQueryData(keys.cohortRows(DEMO_PID, BQ), one)
  qc.setQueryData(keys.cohortRows(DEMO_PID, BQPHASE), one)
  qc.setQueryData(keys.cohortRows(DEMO_PID, BVARPHASE), one)
  qc.setQueryData(keys.cohortRows(DEMO_PID, BSEND), one)
  return render(
    <QueryClientProvider client={qc}>
      <CohortEditor />
    </QueryClientProvider>,
  )
}

const caseIds = () => Array.from(document.querySelectorAll('.cohort-row-case .cohort-cell-id')).map((el) => el.textContent)

beforeEach(() => {
  useWorkbench.setState({ pid: DEMO_PID })
  useCohort.setState({ pid: null, byProject: {}, group: null, pinned: [], expanded: {}, filters: EMPTY_FILTERS })
  useCohort.getState().openProject(DEMO_PID)
  useCohort.getState().setGroup({ origin: 'metadata', category: 'equipment' })
  useExplorer.setState({ pid: null, byProject: {}, filter: {}, expanded: {}, order: [] })
  useLayout.setState({ activeView: 'cohort' })
})

test('a variable filter shows as a removable chip and narrows the grid', () => {
  renderGrid()
  expect(caseIds()).toEqual(['case-1', 'case-2'])
  expect(screen.queryByText('Clear filters')).not.toBeInTheDocument()
  act(() => useCohort.getState().addVarValue('manufacturer', 'SIEMENS'))
  expect(screen.getByText('manufacturer: SIEMENS')).toBeInTheDocument()
  expect(caseIds()).toEqual(['case-1'])
  fireEvent.click(screen.getByRole('button', { name: 'Remove filter: manufacturer: SIEMENS' }))
  expect(screen.queryByText('manufacturer: SIEMENS')).not.toBeInTheDocument()
  expect(caseIds()).toEqual(['case-1', 'case-2'])
})

test('phase and text filters show as chips and clear together', () => {
  renderGrid()
  fireEvent.change(screen.getByRole('combobox', { name: 'Phase' }), { target: { value: 'NC' } })
  expect(screen.getByText('Phase: NC')).toBeInTheDocument()
  expect(caseIds()).toEqual(['case-1'])
  const box = screen.getByRole('textbox', { name: 'Case or patient ID' })
  fireEvent.change(box, { target: { value: 'case_' } })
  fireEvent.keyDown(box, { key: 'Enter' })
  expect(screen.getByText('Case or patient ID: case_')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
  expect(screen.queryByText('Phase: NC')).not.toBeInTheDocument()
  expect(screen.queryByText('Case or patient ID: case_')).not.toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Case or patient ID' })).toHaveValue('')
  expect(screen.getByRole('combobox', { name: 'Phase' })).toHaveValue('')
})

test('the filters persist per project', () => {
  renderGrid()
  act(() => {
    useCohort.getState().addVarValue('manufacturer', 'SIEMENS')
    useCohort.getState().setPhase('NC')
  })
  expect(useCohort.getState().byProject[DEMO_PID]?.filters).toEqual({ vars: { manufacturer: ['SIEMENS'] }, phase: 'NC', q: '' })
  const stored = JSON.parse(localStorage.getItem('rw.cohort.state') ?? '{}')
  expect(stored.state.byProject[DEMO_PID].filters).toEqual({ vars: { manufacturer: ['SIEMENS'] }, phase: 'NC', q: '' })
  useWorkbench.setState({ pid: 'other' })
  useCohort.getState().openProject('other')
  expect(useCohort.getState().filters).toEqual(EMPTY_FILTERS)
  useCohort.getState().openProject(DEMO_PID)
  expect(useCohort.getState().filters).toEqual({ vars: { manufacturer: ['SIEMENS'] }, phase: 'NC', q: '' })
})

test('send to explorer applies the filters in the Explorer and shows its Project view', () => {
  renderGrid()
  act(() => {
    useCohort.getState().addVarValue('manufacturer', 'SIEMENS')
    useCohort.getState().addVarValue('manufacturer_model', 'Vida 64')
    useCohort.getState().addVarValue('manufacturer_model', 'Vida 64b')
    useCohort.getState().setPhase('NC')
    useCohort.getState().setQ('case_')
  })
  fireEvent.click(screen.getByRole('button', { name: 'Send to Explorer' }))
  const f = useExplorer.getState().filter
  // The Explorer keeps one value per variable; a multi-value filter sends its first
  expect(f.vars).toEqual({ manufacturer: 'SIEMENS', manufacturer_model: 'Vida 64' })
  expect(f.phase).toBe('NC')
  expect(f.q).toBe('case_')
  expect(useLayout.getState().activeView).toBe('project')
})
