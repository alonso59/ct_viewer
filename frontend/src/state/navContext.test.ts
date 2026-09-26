// AUD-A1-04: position of the active case / item in a navigation list
import { navPosition, uniqueEntries } from './navContext'

const entries = [
  { caseId: 'c1', itemId: 'c1.a' },
  { caseId: 'c1', itemId: 'c1.b' },
  { caseId: 'c2', itemId: null },
]
const ctx = (index: number) => ({ label: 'Queue', entries, index })

test('the stepped-to entry wins, then the exact item, then the case', () => {
  expect(navPosition(ctx(1), 'c1', 'c1.b')).toBe(1)
  expect(navPosition(ctx(0), 'c1', 'c1.b')).toBe(1)
  expect(navPosition(ctx(0), 'c1', 'c1.z')).toBe(0)
  expect(navPosition(ctx(0), 'c2', 'c2.q')).toBe(2)
  expect(navPosition(ctx(0), 'c3', null)).toBeNull()
  expect(navPosition({ label: null, entries, index: 0 }, 'c1', 'c1.a')).toBeNull()
})

test('repeated rows are listed once, in order', () => {
  expect(uniqueEntries([...entries, { caseId: 'c1', itemId: 'c1.a' }])).toEqual(entries)
})
