// AUD-A1-19 (NFR-17, API-07): a path to open travels in the history state, never in the URL.
import type { NavigateFunction } from 'react-router'

import { openPath, pendingPath } from './openNavigate'

test('openPath navigates to /open with the path in the state only', () => {
  const calls: unknown[][] = []
  const navigate = ((...args: unknown[]) => void calls.push(args)) as unknown as NavigateFunction
  openPath(navigate, '/data/DOE^JANE/ct')
  expect(calls).toEqual([['/open', { state: { openPath: '/data/DOE^JANE/ct' } }]])
  expect(pendingPath({ openPath: '/data/DOE^JANE/ct' })).toBe('/data/DOE^JANE/ct')
  for (const s of [null, undefined, {}, { openPath: '' }, { openPath: 3 }]) expect(pendingPath(s)).toBeNull()
})
