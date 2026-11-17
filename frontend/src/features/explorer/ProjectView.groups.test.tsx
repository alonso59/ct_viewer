// @vitest-environment jsdom
// ADR-0057 / UI-08 on the recorded API (TST-04): an expanded case lists its scans under exam and
// series rows, which fold with the mouse and ←/→; a phase filter hides a group with no match.
import * as RTooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useMemo } from 'react'

import '../../i18n'
import { api, type ItemRecord } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { ProjectView } from './ProjectView'
import { useExplorer } from './store'

// Lay out all rows in jsdom; scroll geometry is verified in the browser.
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => useMemo(() => ({
    measure: () => {},
    scrollToIndex: () => {},
    getTotalSize: () => count * 22,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, size: 22, start: index * 22 })),
  }), [count]),
}))

afterEach(() => {
  vi.restoreAllMocks()
  useWorkbench.setState({ pid: null })
  useExplorer.setState({ filter: {}, expanded: {}, collapsed: {}, order: [] })
})

async function mountMr() {
  const real = await api.getCase(DEMO_PID, 'case_00001')
  const base = real.items.find((i) => i.scope === 'complete')!
  const mk = (idx: string, extra: Record<string, unknown>, phase: string): ItemRecord => ({
    ...base, item_id: `case_00001.${idx}.complete.-`, scan_idx: idx, extra, phase: { ...base.phase, canonical: phase },
  })
  const items = [
    mk('203', { study_uid: 'S1', days_from_first_scan: '0', series_uid: 'D#t2', series_number: '7' }, 'LA'),
    mk('155', { study_uid: 'S1', days_from_first_scan: '0', series_uid: 'D', series_number: '7', series_description: 'dyn' }, 'NC'),
    mk('144', { study_uid: 'S1', days_from_first_scan: '0', series_uid: 'A', series_number: '10' }, 'NA'),
    mk('301', { study_uid: 'S2', days_from_first_scan: '84', series_uid: 'T', series_number: '3' }, 'NA'),
  ]
  vi.spyOn(api, 'getCase').mockResolvedValue({ ...real, items })
  vi.spyOn(api, 'listCases').mockResolvedValue([real.summary])
  useWorkbench.setState({ pid: DEMO_PID })
  useExplorer.setState({ filter: {}, expanded: { case_00001: true }, collapsed: {}, order: [] })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RTooltip.Provider>
        <ProjectView />
      </RTooltip.Provider>
    </QueryClientProvider>,
  )
}

test('exam, series and part rows, in reading order; UIDs only in the tooltip', async () => {
  await mountMr()
  await screen.findByText('Exam · day 84', {}, { timeout: 3_000 })
  // case · exam day 0 · series 7 · 155 · 203 · 144 (one-part series: no row) · exam day 84 · 301
  expect(screen.getAllByRole('treeitem').map((r) => r.getAttribute('aria-level'))).toEqual(['1', '2', '3', '4', '4', '3', '2', '3'])
  expect(screen.getByText('Series 7 · dyn').closest('[role="treeitem"]')).toHaveAttribute('title', 'D')
  expect(screen.getByText('Exam · day 0').closest('[role="treeitem"]')).toHaveAttribute('title', 'S1')
  const scans = screen.getAllByRole('treeitem').filter((r) => r.classList.contains('pv-item')).map((r) => /Scan (\d+)/.exec(r.textContent ?? '')?.[1])
  expect(scans).toEqual(['155', '203', '144', '301'])
  expect(screen.getByText('Scan 203 t2 · Full scan')).toBeInTheDocument()
})

test('a group folds with a click and with ←/→, and stays folded for the project', async () => {
  await mountMr()
  const exam = (await screen.findByText('Exam · day 0', {}, { timeout: 3_000 })).closest('[role="treeitem"]')!
  fireEvent.click(exam)
  expect(exam).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByText(/Scan 155/)).not.toBeInTheDocument()
  expect(useExplorer.getState().collapsed).toEqual({ 'case_00001/exam:S1': true })
  const tree = screen.getByRole('tree')
  // cursor on the exam row (the click put it there), → opens it again
  fireEvent.keyDown(tree, { key: 'ArrowRight' })
  await waitFor(() => expect(screen.getByText(/Scan 155/)).toBeInTheDocument())
  fireEvent.keyDown(tree, { key: 'ArrowLeft' })
  await waitFor(() => expect(screen.queryByText(/Scan 155/)).not.toBeInTheDocument())
})

test('the phase filter hides groups without a matching scan', async () => {
  await mountMr()
  await screen.findByText('Exam · day 84', {}, { timeout: 3_000 })
  act(() => useExplorer.getState().setFilter({ phase: 'LA' }))
  await waitFor(() => expect(screen.queryByText('Exam · day 84')).not.toBeInTheDocument())
  expect(screen.getByText('Series 7 · dyn')).toBeInTheDocument()
  expect(screen.getAllByRole('treeitem').filter((r) => r.classList.contains('pv-item'))).toHaveLength(1)
})
