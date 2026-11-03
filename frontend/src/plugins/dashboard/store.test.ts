// @vitest-environment jsdom
// UI-13 (DB-02): a run's filters and colouring are kept across reloads; its selection is not.
import { useDashboardStore } from './store'

test('filters are saved per run, the selection is not', () => {
  const s = useDashboardStore.getState()
  s.setFilters('run-1', { phase: ['NP'] })
  s.select('run-1', ['case_00001.01.complete.-'])
  const saved = JSON.parse(localStorage.getItem('rw.dashboard') ?? '{}') as { state: { runs: Record<string, Record<string, unknown>> } }
  expect(saved.state.runs['run-1']).toEqual({ filters: { phase: ['NP'] }, colorBy: { kind: 'phase' }, filterVars: [] })
})
