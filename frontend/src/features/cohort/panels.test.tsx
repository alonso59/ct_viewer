// @vitest-environment jsdom
// COH-06..09, COH-13: the column summary adds filters from its bars, compare scans hides equal rows, the DICOM
// tags panel searches, and the CSV leaves out sensitive variables unless chosen.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useMemo } from 'react'
import { vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { api, keys, type CohortCaseRow, type CohortTimeline, type LabelTableInfo, type Project, type Variable } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { registry, useWorkbench } from '../../shell'
import { useReviewer } from '../../state'
import { CohortEditor } from './CohortEditor'
import { gridCsv } from './csv'
import { EMPTY_FILTERS, useCohort } from './store'

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => useMemo(() => ({
    measure: () => {},
    scrollToIndex: () => {},
    getTotalSize: () => count * 22,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, key: index, size: 22, start: index * 22 })),
  }), [count]),
}))

// ECharts needs a canvas; the mock lists the bars as buttons so a click can be tested
vi.mock('../../plugins/dashboard/Chart', () => ({
  palette: () => [],
  axisStyle: () => ({ axisLabel: {} }),
  chartImage: () => '',
  fontSize: () => 12,
  SYMBOLS: ['circle', 'rect', 'triangle'],
  Chart: ({ option, onClick }: { option: { xAxis: { data?: string[] } }; onClick: (p: { dataIndex: number }) => void }) => (
    <div>{(option.xAxis.data ?? []).map((label, dataIndex) => <button key={label} type="button" onClick={() => onClick({ dataIndex })}>{`bar ${label}`}</button>)}</div>
  ),
}))

const v = (name: string, tags: Variable['tags'] = []): Variable => ({
  name, source: 'metadata', type: 'categorical', inferred_type: 'categorical', level: 'scan', group: 'study', origin: 'metadata', category: 'equipment',
  tags, visible: true, confidence: 1, review: false, overridden: false, comparable: false,
  profile: { missing_pct: 0, n_distinct: 2, examples: [], levels: [{ value: 'B', count: 5 }, { value: 'A', count: 3 }] },
})
const CATALOG = [v('manufacturer'), v('manufacturer_model'), v('patient_id', ['sensitive'])]
const ROW: CohortCaseRow = {
  case_id: 'case-1',
  values: { manufacturer: 'Siemens', manufacturer_model: null, patient_id: 'P1' },
  differs: ['manufacturer_model'],
  scans: [
    { scan_idx: 's1', item_id: 'item-1', phase: 'NC', modality: 'CT', values: { manufacturer: 'Siemens', manufacturer_model: 'Vida', patient_id: 'P1' } },
    { scan_idx: 's2', item_id: 'item-2', phase: 'ART', modality: 'CT', values: { manufacturer: 'Siemens', manufacturer_model: 'Flash', patient_id: 'P1' } },
  ],
}
const ALL = ['manufacturer', 'manufacturer_model', 'patient_id']

function renderEditor(seed: (qc: QueryClient) => void) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.project(DEMO_PID), { project_id: DEMO_PID, phase_vocabulary: ['NC', 'ART'], default_seg: 'imported' } as unknown as Project)
  qc.setQueryData(keys.variables(DEMO_PID), CATALOG)
  qc.setQueryData(keys.curationState(DEMO_PID), [])
  qc.setQueryData(keys.cohortRows(DEMO_PID, { columns: ['manufacturer', 'manufacturer_model', 'patient_id'], filters: {}, sort: null, offset: 0, limit: 100 }), { n_cases: 1, n_scans: 2, rows: [ROW] })
  seed(qc)
  return render(<QueryClientProvider client={qc}><CohortEditor /></QueryClientProvider>)
}

beforeEach(() => {
  useWorkbench.setState({ pid: DEMO_PID })
  useCohort.setState({ pid: null, byProject: {}, group: null, pinned: [], expanded: {}, filters: EMPTY_FILTERS, compareCase: null, summaryColumn: null, tagsItem: null, balance: null, timelineCase: null })
  useCohort.getState().openProject(DEMO_PID)
  useCohort.getState().setGroup({ origin: 'metadata', category: 'equipment' })
})

test('a summary bar adds the filter and the table lists the same rows', async () => {
  useCohort.getState().setSummary('manufacturer')
  renderEditor((qc) => qc.setQueryData(keys.cohortSummary(DEMO_PID, { column: 'manufacturer', filters: {} }), { counts: { Siemens: 4, GE: 1 }, other: 0, missing: 2 }))
  fireEvent.click(await screen.findByRole('button', { name: 'bar Siemens' }))
  expect(useCohort.getState().filters.vars).toEqual({ manufacturer: ['Siemens'] })
  fireEvent.click(screen.getByRole('button', { name: 'Show as table' }))
  const table = within(screen.getByRole('region', { name: 'Chart values' }))
  expect(table.getByText('Siemens')).toBeInTheDocument()
  expect(table.getByText('Missing')).toBeInTheDocument()
})

test('compare scans lists the scans as columns and can hide the rows that agree', async () => {
  useCohort.getState().setCompare('case-1')
  renderEditor((qc) =>
    qc.setQueryData(keys.cohortRows(DEMO_PID, { columns: ALL, q: 'case-1', sort: null, offset: 0, limit: 50 }), { n_cases: 1, n_scans: 2, rows: [ROW] }),
  )
  const panel = within(await screen.findByRole('region', { name: 'Compared fields' }))
  expect(panel.getByRole('columnheader', { name: 's1 · NC · CT' })).toBeInTheDocument()
  expect(panel.getByRole('columnheader', { name: 's2 · ART · CT' })).toBeInTheDocument()
  expect(panel.getByText('manufacturer')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Differences only' }))
  expect(panel.queryByText('manufacturer')).not.toBeInTheDocument()
  expect(panel.getByText('manufacturer_model')).toBeInTheDocument()
})

test('the tags panel shows one scan\'s tags and searches them', () => {
  useCohort.getState().setTags('item-1')
  renderEditor((qc) =>
    qc.setQueryData(keys.dicomTags(DEMO_PID, 'item-1'), {
      '00080070': { vr: 'LO', Value: ['SIEMENS'] },
      '00181030': { vr: 'LO', Value: ['Abdomen'] },
    }),
  )
  expect(screen.getByText('0008,0070')).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: 'Search tags' }), { target: { value: 'abdo' } })
  expect(screen.queryByText('0008,0070')).not.toBeInTheDocument()
  expect(screen.getByText('0018,1030')).toBeInTheDocument()
})

test('the CSV has one row per scan and leaves out sensitive variables unless chosen', () => {
  const plain = gridCsv(CATALOG, [ROW], false).trim().split('\n')
  expect(plain[0]).toBe('case_id,scan,phase,modality,manufacturer,manufacturer_model')
  expect(plain).toHaveLength(3)
  expect(plain[1]).toBe('case-1,s1,NC,CT,Siemens,Vida')
  expect(gridCsv(CATALOG, [ROW], true).split('\n')[0]).toBe('case_id,scan,phase,modality,manufacturer,manufacturer_model,patient_id')
})

test('the balance check shows the counts as a table and says which test compared them', async () => {
  useCohort.getState().setBalance({ a: 'manufacturer', b: 'manufacturer_model' })
  renderEditor((qc) =>
    qc.setQueryData(keys.cohortBalance(DEMO_PID, { a: 'manufacturer', b: 'manufacturer_model', filters: {}, test: 'auto' }), {
      unit: 'case', rows: ['GE', 'SIEMENS'], cols: ['A', 'B'], n: 20, missing: 0, excluded_rows: ['PHILIPS'], excluded_cols: [],
      cells: [{ row: 'GE', col: 'A', n: 2, expected: 5 }, { row: 'GE', col: 'B', n: 8, expected: 5 }, { row: 'SIEMENS', col: 'A', n: 8, expected: 5 }, { row: 'SIEMENS', col: 'B', n: 2, expected: 5 }],
      test: 'chi2', reason: 'all expected counts ≥ 5', statistic: 7.2, p: 0.007, cramers_v: 0.6,
    }),
  )
  expect(await screen.findByRole('status')).toHaveTextContent(/χ² test: p = 0\.007.*Left out \(fewer than 5 rows\): PHILIPS/)
  fireEvent.click(screen.getByRole('button', { name: 'Show as table' }))
  const table = within(screen.getByRole('region', { name: 'Chart values' }))
  expect(table.getByText('SIEMENS')).toBeInTheDocument()
})

const EVENTS = {
  table_id: 'E1', slug: 'events', name: 'Events', level: 'event', n_rows: 1, progress: [], created_at: '', updated_at: '',
  columns: [
    { column_id: 'K', slug: 'kind', name: 'Kind', type: 'category', levels: ['Surgery', 'Death'] },
    { column_id: 'D', slug: 'day', name: 'Day', type: 'number', unit: 'days' },
  ],
} as unknown as LabelTableInfo
const TIMELINE: CohortTimeline = {
  case_id: 'case-1', anchor_scan: 's1', followup_days: 40,
  scans: [{ scan_idx: 's1', item_id: 'item-1', phase: 'NC', day: 0 }],
  events: [{ table_id: 'E1', table: 'Events', target: 'case-1#1', kind: 'Surgery', day: 40, values: {} }],
}

function renderTimeline(tables: LabelTableInfo[]) {
  vi.spyOn(api, 'cohortTimeline').mockResolvedValue(TIMELINE)
  vi.spyOn(api, 'listLabelTables').mockResolvedValue(tables)
  useCohort.getState().setTimeline('case-1')
  return renderEditor((qc) => {
    qc.setQueryData(keys.labelTables(DEMO_PID), tables)
    qc.setQueryData(keys.cohortTimeline(DEMO_PID, 'case-1'), TIMELINE)
  })
}

test('the timeline lists a case\'s events, adds one as a new row with its kind and day, and removes one', async () => {
  useReviewer.setState({ name: 'Dr. T' })
  const row = vi.spyOn(api, 'addLabelRow').mockResolvedValue({ table_id: 'E1', target: 'case-1#2', case_id: 'case-1', removed: false })
  const write = vi.spyOn(api, 'writeLabelCells').mockResolvedValue({ n_events: 2 })
  const remove = vi.spyOn(api, 'removeLabelRow').mockResolvedValue({ table_id: 'E1', target: 'case-1#1', case_id: 'case-1', removed: true })
  renderTimeline([EVENTS])
  expect(await screen.findByText('Surgery, day 40 (Events)')).toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox', { name: 'Kind' }), { target: { value: 'Death' } })
  fireEvent.change(screen.getByRole('textbox', { name: 'Day (from the first dated scan)' }), { target: { value: '90,5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add event' }))
  await waitFor(() => expect(row).toHaveBeenCalledWith(DEMO_PID, 'E1', 'case-1', 'Dr. T'))
  await waitFor(() =>
    expect(write).toHaveBeenCalledWith(DEMO_PID, 'E1', [{ column_id: 'K', target: 'case-1#2', value: 'Death' }, { column_id: 'D', target: 'case-1#2', value: '90.5' }], 'Dr. T'),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Remove Surgery on day 40' }))
  await waitFor(() => expect(remove).toHaveBeenCalledWith(DEMO_PID, 'E1', 'case-1#1', 'Dr. T'))
  vi.restoreAllMocks()
})

test('the timeline points to the Labeling view when there is no event table, and is read-only on a view link', async () => {
  const { unmount } = renderTimeline([])
  expect(await screen.findByText(/Create an event table in the Labeling view/)).toBeInTheDocument()
  unmount()
  registry.setReadOnly(true)
  renderTimeline([EVENTS])
  expect(await screen.findByText('Surgery, day 40 (Events)')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Add event' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Remove Surgery on day 40' })).not.toBeInTheDocument()
  registry.setReadOnly(false)
})
