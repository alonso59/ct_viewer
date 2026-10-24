// @vitest-environment jsdom
// UI-28 / TSK-16: browser persistence holds references/preferences, never job authority or PHI.
import { beforeEach, expect, test } from 'vitest'

import { useConverter } from './store'

beforeEach(() => { useConverter.getState().close(); localStorage.clear() })

test('persists only the selected operation ID and window preference', () => {
  useConverter.getState().show({ source: '/data/private/patient', pid: 'private-project' })
  useConverter.getState().patch({ operationId: 'opaque-operation' })
  useConverter.getState().minimize()
  const stored = localStorage.getItem('rw.converter')
  expect(stored).not.toBeNull()
  expect(JSON.parse(stored!).state).toEqual({ operationId: 'opaque-operation', minimized: true })
  expect(stored).not.toContain('patient')
  expect(stored).not.toContain('private-project')
})

test('attaches a server operation without restoring browser-owned progress or source paths', () => {
  useConverter.getState().attach('server-operation', true)
  expect(useConverter.getState()).toMatchObject({ operationId: 'server-operation', open: true, minimized: true, source: null, scan: null, run: null })
})

test('starting another draft is explicit and clears the selected reference', () => {
  useConverter.getState().attach('running-operation')
  useConverter.setState({ working: true })
  useConverter.getState().show({ source: '/data/other' })
  expect(useConverter.getState().operationId).toBe('running-operation')
  useConverter.getState().newOperation()
  expect(useConverter.getState()).toMatchObject({ operationId: null, open: true, working: false, source: null })
})
