// @vitest-environment jsdom
// UI-08 / VAR-10 / PHS-03 / DB-04: shared filters, independent removal and phase/item intersection.
import * as RTooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useMemo } from 'react'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useSettings, useViewerSync } from '../../state'
import { ProjectView } from './ProjectView'
import { SearchView } from './SearchView'
import { useExplorer } from './store'
import * as navigation from './navigate'

// Lay out all rows in jsdom; scroll geometry is verified in the browser.
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => useMemo(() => ({
    measure: () => {},
    scrollToIndex: () => {},
    getTotalSize: () => count * 22,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, size: 22, start: index * 22 })),
  }), [count]),
}))

beforeEach(() => {
  useWorkbench.setState({ pid: DEMO_PID })
  useExplorer.setState({ filter: {}, expanded: {}, order: [] })
  useSettings.setState({ rowDensity: 'compact' })
})

afterEach(() => vi.restoreAllMocks())

function mount(view = <ProjectView />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const result = render(<QueryClientProvider client={qc}><RTooltip.Provider>{view}</RTooltip.Provider></QueryClientProvider>)
  return { ...result, qc }
}

test('UI-08 / VAR-10: combine conditions, collapse panel, remove one and clear all', async () => {
  const requests = vi.spyOn(api, 'listCases')
  mount()
  fireEvent.change(screen.getByRole('textbox', { name: 'Filter cases' }), { target: { value: 'case_00001' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'Phase' }), { target: { value: 'UNK' } })
  fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
  const panel = screen.getByRole('region', { name: 'Filters' })
  expect(panel).toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox', { name: 'Curation status' }), { target: { value: 'not_reviewed' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'QC warnings' }), { target: { value: 'any' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'VOI' }), { target: { value: 'none' } })
  await waitFor(() => expect(requests).toHaveBeenLastCalledWith(DEMO_PID, expect.objectContaining({ phase: 'UNK', status: 'not_reviewed', warning: 'any', voi: 'none' })))

  fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
  expect(screen.queryByRole('region', { name: 'Filters' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Filters' })).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(screen.getByRole('button', { name: 'Remove filter: Phase: UNK' }))
  expect(useExplorer.getState().filter).toMatchObject({ phase: '', status: 'not_reviewed', warning: 'any', voi: 'none', q: 'case_00001' })

  act(() => useExplorer.getState().setVarFilter('patient_age', '40..65'))
  fireEvent.click(screen.getByRole('button', { name: 'Remove filter: patient_age: 40..65' }))
  expect(useExplorer.getState().filter.vars).toEqual({})
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
  expect(useExplorer.getState().filter).toEqual({})
  expect(screen.getByRole('textbox', { name: 'Filter cases' })).toHaveValue('')
})

test('UI-08 / NFR-03: text search updates rows, count and navigation without another cohort request', async () => {
  const { summary } = await api.getCase(DEMO_PID, 'case_00001')
  const requests = vi.spyOn(api, 'listCases').mockResolvedValue([
    { ...summary, case_id: 'Alpha', patient_id: 'Study-42' },
    { ...summary, case_id: 'Beta', patient_id: 'Other patient' },
  ])
  mount()
  await waitFor(() => expect(screen.getAllByRole('treeitem')).toHaveLength(2))
  const originalRequests = requests.mock.calls.length
  const search = screen.getByRole('textbox', { name: 'Filter cases' })
  fireEvent.change(search, { target: { value: ' STUDY-42 ' } })
  expect(screen.getAllByRole('treeitem')).toHaveLength(1)
  expect(screen.getByRole('treeitem')).toHaveTextContent('Alpha')
  expect(screen.getByText('1 case')).toBeInTheDocument()
  await waitFor(() => expect(useExplorer.getState().order).toEqual(['Alpha']))
  fireEvent.change(search, { target: { value: 'BETA' } })
  expect(screen.getByRole('treeitem')).toHaveTextContent('Beta')
  await waitFor(() => expect(useExplorer.getState().order).toEqual(['Beta']))
  fireEvent.change(search, { target: { value: ' ' } })
  expect(screen.getAllByRole('treeitem')).toHaveLength(2)
  expect(screen.getByText('2 cases')).toBeInTheDocument()
  expect(requests).toHaveBeenCalledTimes(originalRequests)
})

test('PHS-03 / DB-04: phase hides other scan rows and intersects the dashboard selection', async () => {
  const detail = await api.getCase(DEMO_PID, 'case_00001')
  vi.spyOn(api, 'listCases').mockResolvedValue([detail.summary])
  act(() => useExplorer.setState({ expanded: { case_00001: true }, filter: { phase: 'CMP' } }))
  mount()
  const itemRows = () => screen.getAllByRole('treeitem').filter((r) => r.getAttribute('aria-level') === '2')
  await waitFor(() => expect(itemRows()).toHaveLength(1))
  expect(itemRows()[0]).toHaveTextContent('CMP')
  expect(itemRows()[0]).toHaveTextContent('Scan 02')

  act(() => useExplorer.getState().setItemIds(['case_00001.01.complete.-']))
  await waitFor(() => expect(itemRows()).toHaveLength(0))
  act(() => useExplorer.getState().setItemIds(['case_00001.02.complete.-']))
  await waitFor(() => expect(itemRows()).toHaveLength(1))
  fireEvent.click(screen.getByRole('button', { name: 'Remove filter: Phase: CMP' }))
  expect(itemRows()).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Clear the item filter' }))
  await waitFor(() => expect(itemRows()).toHaveLength(detail.items.length))
})

test('VAR-10: Search and Project use the same controls and keep their conditions', async () => {
  const { unmount } = mount(<SearchView />)
  fireEvent.change(screen.getByRole('combobox', { name: 'Phase' }), { target: { value: 'NP' } })
  const age = await screen.findByRole('textbox', { name: 'patient_age minimum' })
  fireEvent.change(age, { target: { value: '40' } })
  fireEvent.blur(age)
  expect(useExplorer.getState().filter.vars).toEqual({ patient_age: '40..' })
  unmount()
  mount()
  expect(screen.getByRole('combobox', { name: 'Phase' })).toHaveValue('NP')
  expect(screen.getByRole('button', { name: 'Remove filter: patient_age: 40..' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
  expect(await screen.findByRole('textbox', { name: 'patient_age minimum' })).toHaveValue('40')
})

test('PHS-01: case and scan phases stay read-only and colored during navigation', async () => {
  const detail = await api.getCase(DEMO_PID, 'case_00001')
  const items = detail.items.slice(0, 2).map((item, i) => ({ ...item, phase: { ...item.phase, canonical: i === 0 ? 'NP' : 'UNK' } }))
  const summary = { ...detail.summary, phases: ['NP', 'UNK'] }
  vi.spyOn(api, 'getCase').mockResolvedValue({ ...detail, summary, items })
  vi.spyOn(api, 'listCases').mockResolvedValue([summary])
  const append = vi.spyOn(api, 'appendPhase')
  const open = vi.spyOn(navigation, 'openFromExplorer').mockImplementation(() => {})
  useExplorer.setState({ expanded: { case_00001: true } })
  useSettings.setState({ rowDensity: 'thumbnails' })
  useViewerSync.setState({ activeCaseId: 'case_00001', activeItemId: items[0]!.item_id })
  mount()
  await waitFor(() => expect(screen.getAllByRole('treeitem')).toHaveLength(3))
  const rows = screen.getAllByRole('treeitem')
  for (const row of rows) {
    for (const chip of row.querySelectorAll('[data-phase]')) {
      expect(chip.tagName).toBe('SPAN')
      expect(chip).toHaveAttribute('data-tone', chip.getAttribute('data-phase') === 'UNK' ? 'warn' : 'accent')
    }
  }
  const itemRows = rows.filter((r) => r.getAttribute('aria-level') === '2')
  expect(itemRows[0]).toHaveAttribute('aria-selected', 'true')
  for (const row of itemRows) {
    fireEvent.mouseOver(row)
    fireEvent.focusIn(row)
    expect(row.querySelector('button')).toBeNull()
    fireEvent.click(row.querySelector('[data-phase]')!)
  }
  expect(open).toHaveBeenCalledTimes(2)
  expect(append).not.toHaveBeenCalled()
})
