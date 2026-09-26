// AUD-A1-04 (CUR-08, UI-09, DB-04): navigation context and "next unreviewed case"
import type { CaseSummary } from '../../api'
import { navPosition, uniqueEntries, useNavContext, useViewerSync } from '../../state'

const opened: unknown[] = []
vi.mock('../../shell', async (orig) => {
  const m = await orig<typeof import('../../shell')>()
  return { ...m, openEditor: (type: string, params: unknown) => opened.push([type, params]) }
})

const { openFromExplorer, openInContext, pickNextUnreviewed, registerExplorer } = await import('./index')
const { registry } = await import('../../shell')
registerExplorer()

beforeEach(() => {
  opened.length = 0
  useNavContext.getState().clear()
})

const at = (caseId: string, itemId: string | null) => useViewerSync.setState({ activeCaseId: caseId, activeItemId: itemId })

test('a case opened from a list follows that list on Alt+↓ / Alt+↑', () => {
  const rows = [
    { caseId: 'c9', itemId: 'c9.i1' },
    { caseId: 'c9', itemId: 'c9.i1' }, // same item, another label row: listed once
    { caseId: 'c3', itemId: 'c3.i2' },
    { caseId: 'c5', itemId: null },
  ]
  openInContext('Outliers', rows, 2)
  expect(opened).toEqual([['case', { caseId: 'c3', itemId: 'c3.i2' }]])
  expect(useNavContext.getState()).toMatchObject({ label: 'Outliers', index: 1, entries: uniqueEntries(rows) })
  at('c3', 'c3.i2')
  registry.commands.get('explorer.nextCase')?.run()
  expect(opened.at(-1)).toEqual(['case', { caseId: 'c5', itemId: null }])
  at('c5', 'c5.i7')
  expect(navPosition(useNavContext.getState(), 'c5', 'c5.i7')).toBe(2)
  registry.commands.get('explorer.prevCase')?.run()
  at('c3', 'c3.i2')
  registry.commands.get('explorer.prevCase')?.run()
  expect(opened.at(-1)).toEqual(['case', { caseId: 'c9', itemId: 'c9.i1' }])
})

test('an Explorer open or × drops the context; outside the list Alt+↓ is Explorer order', () => {
  openInContext('Correction queue', [{ caseId: 'c2', itemId: 'c2.a' }], 0)
  expect(navPosition(useNavContext.getState(), 'c8', null)).toBeNull()
  openFromExplorer('c1', null)
  expect(useNavContext.getState().label).toBeNull()
  openInContext('Problems', [{ caseId: 'c2', itemId: 'c2.a' }], 0)
  registry.commands.get('explorer.clearNavContext')?.run()
  expect(useNavContext.getState().label).toBeNull()
})

const cs = (id: string, review_state: CaseSummary['review_state'], excluded = false) => ({ case_id: id, review_state, excluded }) as CaseSummary

test('next unreviewed: after the active case, wrapping, skipping reviewed and excluded (CUR-08)', () => {
  const list = [cs('a', 'reviewed'), cs('b', 'partial'), cs('c', 'reviewed'), cs('d', 'not_reviewed', true), cs('e', 'not_reviewed')]
  expect(pickNextUnreviewed(list, 'b')?.case_id).toBe('e')
  expect(pickNextUnreviewed(list, 'e')?.case_id).toBe('b')
  expect(pickNextUnreviewed(list, null)?.case_id).toBe('b')
  expect(pickNextUnreviewed([cs('a', 'reviewed')], 'a')).toBeUndefined()
})
