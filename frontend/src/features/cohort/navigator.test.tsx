// @vitest-environment jsdom
// COH-02: the navigator lists the origin groups (Metadata by category) with variable
// counts, searches field names, and keeps the open group and pins per project.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { keys, type Variable, type VariableCategory, type VariableOrigin } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { CohortView } from './CohortView'
import { EMPTY_FILTERS, useCohort } from './store'

const v = (name: string, origin: VariableOrigin, category: VariableCategory | null, extra: Partial<Variable> = {}): Variable => ({
  name, source: 'metadata', type: 'categorical', inferred_type: 'categorical', level: 'case', group: 'study', origin, category,
  tags: [], visible: true, confidence: 1, review: false, overridden: false, comparable: false,
  profile: { missing_pct: 0, n_distinct: 2, examples: [], levels: [{ value: 'B', count: 5 }, { value: 'A', count: 3 }] },
  ...extra,
})

const CATALOG: Variable[] = [
  v('manufacturer', 'metadata', 'equipment'),
  v('manufacturer_model', 'metadata', 'equipment'),
  v('kvp', 'metadata', 'technique'),
  v('status', 'metadata', 'provenance', { type: 'constant', inferred_type: 'constant', profile: { missing_pct: 0, n_distinct: 1, examples: ['ok'], levels: [{ value: 'ok', count: 90 }] } }),
  v('phase_effective', 'review', null),
  v('tumor_size', 'clinical', null, { visible: false }),
  v('size_bin', 'derived', null),
]

function renderNav() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(keys.variables(DEMO_PID), CATALOG)
  return render(
    <QueryClientProvider client={qc}>
      <CohortView />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useWorkbench.setState({ pid: DEMO_PID })
  useCohort.setState({ pid: null, byProject: {}, group: null, pinned: [], expanded: {}, filters: EMPTY_FILTERS })
  useCohort.getState().openProject(DEMO_PID)
})

test('origin groups in fixed order, Metadata split by category, variable counts', () => {
  const { container } = renderNav()
  const labels = Array.from(container.querySelectorAll('button.cohort-group')).map((b) => b.textContent)
  expect(labels).toEqual(['Equipment2', 'Technique1', 'Provenance1', 'Review1', 'Clinical & labels1', 'Derived1'])
  // Constant variables list as "Same for all: value" instead of a column
  fireEvent.click(screen.getByRole('button', { name: /^Provenance/ }))
  expect(screen.getByText('Same for all: ok')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Pin status/ })).not.toBeInTheDocument()
})

test('Metadata fields without a category stay reachable under Other', () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(keys.variables(DEMO_PID), [v('source_kind', 'metadata', null, { type: 'constant', inferred_type: 'constant' })])
  const { container } = render(<QueryClientProvider client={qc}><CohortView /></QueryClientProvider>)
  expect(Array.from(container.querySelectorAll('button.cohort-group')).map((b) => b.textContent)).toEqual(['Other1'])
})

test('search filters field names; a hit selects its group or category', () => {
  renderNav()
  fireEvent.change(screen.getByRole('textbox', { name: 'Search fields' }), { target: { value: 'kvp' } })
  expect(screen.getByRole('button', { name: 'kvp' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Equipment/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'kvp' }))
  expect(useCohort.getState().group).toEqual({ origin: 'metadata', category: 'technique' })
  expect(screen.getByRole('button', { name: /^Technique/ }).getAttribute('aria-expanded')).toBe('true')
  expect(screen.getByRole('textbox', { name: 'Search fields' })).toHaveValue('')
  fireEvent.change(screen.getByRole('textbox', { name: 'Search fields' }), { target: { value: 'zzz' } })
  expect(screen.getByText('No matching fields')).toBeInTheDocument()
})

test('the open group and pins persist per project', () => {
  renderNav()
  fireEvent.click(screen.getByRole('button', { name: /^Technique/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Pin kvp' }))
  expect(useCohort.getState().pinned).toEqual(['kvp'])
  expect(useCohort.getState().byProject[DEMO_PID]).toEqual({ group: { origin: 'metadata', category: 'technique' }, pinned: ['kvp'], expanded: {}, filters: EMPTY_FILTERS })
  const stored = JSON.parse(localStorage.getItem('rw.cohort.state') ?? '{}')
  expect(stored.state.byProject[DEMO_PID].pinned).toEqual(['kvp'])
  // A second project gets its own state
  useWorkbench.setState({ pid: 'other' })
  useCohort.getState().openProject('other')
  expect(useCohort.getState().pinned).toEqual([])
  expect(useCohort.getState().group).toBeNull()
  useCohort.getState().openProject(DEMO_PID)
  expect(useCohort.getState().pinned).toEqual(['kvp'])
  expect(useCohort.getState().group).toEqual({ origin: 'metadata', category: 'technique' })
})
