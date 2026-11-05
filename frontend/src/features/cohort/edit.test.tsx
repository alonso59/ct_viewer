// @vitest-environment jsdom
// COH-12: a Clinical & labels cell edits in place through the label table's write path; other
// origins, reference columns and view-only links stay read-only.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useMemo } from 'react'
import { vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { api, keys, type CohortCaseRow, type LabelTableInfo, type Project, type Variable } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { registry, useWorkbench } from '../../shell'
import { useReviewer } from '../../state'
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

const v = (name: string, origin: Variable['origin'], type: Variable['type'] = 'categorical'): Variable => ({
  name, source: origin === 'clinical' ? 'layer' : 'metadata', type, inferred_type: type, level: 'case', group: 'study', origin,
  category: origin === 'metadata' ? 'equipment' : null, tags: [], visible: true, confidence: 1, review: false, overridden: false, comparable: false,
  profile: { missing_pct: 0, n_distinct: 2, examples: [], levels: [] },
})
const CATALOG = [v('lbl.review.grade', 'clinical'), v('lbl.review.mirror', 'clinical'), v('manufacturer', 'metadata')]
const TABLE = {
  table_id: 'T1', slug: 'review', name: 'Review', level: 'case', n_rows: 2, progress: [], created_at: '', updated_at: '',
  columns: [
    { column_id: 'C1', slug: 'grade', name: 'Grade', type: 'category', levels: ['G1', 'G2'] },
    { column_id: 'C2', slug: 'mirror', name: 'Mirror', type: 'text', ref: 'manufacturer' },
  ],
} as unknown as LabelTableInfo
const COLUMNS = ['lbl.review.grade', 'lbl.review.mirror']
const ROWS: CohortCaseRow[] = ['case-1', 'case-2'].map((case_id, i) => ({
  case_id,
  values: { 'lbl.review.grade': i ? 'G2' : null, 'lbl.review.mirror': 'x' },
  scans: [{ scan_idx: 's1', item_id: `item-${i}`, phase: 'NC', modality: 'CT', values: { 'lbl.review.grade': i ? 'G2' : null, 'lbl.review.mirror': 'x' } }],
}))

function renderGrid() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.project(DEMO_PID), { project_id: DEMO_PID, phase_vocabulary: ['NC'], default_seg: 'imported' } as unknown as Project)
  qc.setQueryData(keys.variables(DEMO_PID), CATALOG)
  qc.setQueryData(keys.curationState(DEMO_PID), [])
  qc.setQueryData(keys.labelTables(DEMO_PID), [TABLE])
  qc.setQueryData(keys.cohortRows(DEMO_PID, { columns: COLUMNS, filters: {}, sort: null, offset: 0, limit: 100 }), { n_cases: 2, n_scans: 2, rows: ROWS })
  return render(<QueryClientProvider client={qc}><CohortEditor /></QueryClientProvider>)
}

const firstCell = () => document.querySelector('.cohort-row-case .cohort-cell') as HTMLElement

beforeEach(() => {
  useWorkbench.setState({ pid: DEMO_PID })
  useReviewer.setState({ name: 'Dr. T' })
  useCohort.setState({ pid: null, byProject: {}, group: null, pinned: [], expanded: {}, filters: EMPTY_FILTERS, sort: null, editing: null })
  useCohort.getState().openProject(DEMO_PID)
  useCohort.getState().setGroup({ origin: 'clinical', category: null })
  useCellMenu.setState({ target: null })
  registry.setReadOnly(false)
})

afterEach(() => {
  registry.setReadOnly(false)
  vi.restoreAllMocks()
})

test('a double click edits a clinical cell and writes one label event to the table', async () => {
  const write = vi.spyOn(api, 'writeLabelCells').mockResolvedValue({ n_events: 1 })
  renderGrid()
  fireEvent.doubleClick(firstCell().firstElementChild as HTMLElement)
  const editor = await screen.findByRole('combobox', { name: 'Grade' })
  fireEvent.change(editor, { target: { value: 'G1' } })
  await waitFor(() => expect(write).toHaveBeenCalledWith(DEMO_PID, 'T1', [{ column_id: 'C1', target: 'case-1', value: 'G1' }], 'Dr. T'))
})

test('the cell menu offers edit, fill and paste on a clinical cell, and fill writes every filtered case', async () => {
  const write = vi.spyOn(api, 'writeLabelCells').mockResolvedValue({ n_events: 2 })
  vi.spyOn(api, 'cohortRows').mockResolvedValue({ n_cases: 2, n_scans: 2, rows: ROWS })
  renderGrid()
  useCellMenu.getState().open({ caseId: 'case-2', scanIdx: null, itemId: 'item-1', column: 'lbl.review.grade', value: 'G2', label: 'grade', x: 1, y: 1 })
  expect(await screen.findByRole('menuitem', { name: 'Edit value' })).toBeInTheDocument()
  expect(screen.getByRole('menuitem', { name: 'Paste values from here down' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Fill the filtered rows with this value' }))
  await waitFor(() =>
    expect(write).toHaveBeenCalledWith(DEMO_PID, 'T1', [{ column_id: 'C1', target: 'case-1', value: 'G2' }, { column_id: 'C1', target: 'case-2', value: 'G2' }], 'Dr. T'),
  )
})

test('reference columns, other origins and view-only links are not editable', async () => {
  renderGrid()
  // the mirror column is the second cell: no editable wrapper
  const cells = document.querySelectorAll('.cohort-row-case .cohort-cell')
  expect(cells[0]?.querySelector('.cohort-editable')).not.toBeNull()
  expect(cells[1]?.querySelector('.cohort-editable')).toBeNull()
  useCellMenu.getState().open({ caseId: 'case-1', scanIdx: null, itemId: 'item-0', column: 'lbl.review.mirror', value: 'x', label: 'mirror', x: 1, y: 1 })
  await screen.findByRole('menuitem', { name: 'Copy value' })
  expect(screen.queryByRole('menuitem', { name: 'Edit value' })).not.toBeInTheDocument()
})

test('a view-only workbench never shows the edit actions', async () => {
  registry.setReadOnly(true)
  renderGrid()
  expect(document.querySelector('.cohort-editable')).toBeNull()
  useCellMenu.getState().open({ caseId: 'case-1', scanIdx: null, itemId: 'item-0', column: 'lbl.review.grade', value: 'G1', label: 'grade', x: 1, y: 1 })
  await screen.findByRole('menuitem', { name: 'Copy value' })
  expect(screen.queryByRole('menuitem', { name: 'Edit value' })).not.toBeInTheDocument()
})
