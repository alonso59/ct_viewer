// @vitest-environment jsdom
// UI-13: the Explorer filter and expanded cases are each project's own and kept across reloads;
// another project starts unfiltered.
import { useExplorer } from './store'

test('each project keeps its own filter and expanded cases', () => {
  const s = () => useExplorer.getState()
  s().openProject('A')
  s().setFilter({ phase: 'NP' })
  s().toggle('case_00001', true)
  s().openProject('B')
  expect(s().filter).toEqual({})
  expect(s().expanded).toEqual({})
  s().openProject('A')
  expect(s().filter).toEqual({ phase: 'NP' })
  expect(s().expanded).toEqual({ case_00001: true })
  const saved = JSON.parse(localStorage.getItem('rw.explorer.state') ?? '{}') as { state: { byProject: Record<string, unknown> } }
  expect(saved.state.byProject.A).toEqual({ filter: { phase: 'NP' }, expanded: { case_00001: true } })
})
