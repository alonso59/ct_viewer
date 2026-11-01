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
  expect(JSON.parse(stored!).state).toEqual({ operationId: 'opaque-operation', batchPlanId: null, minimized: true })
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

test('keeps the batch plan reference across closing and persists only its ID', () => {
  useConverter.setState({ batchPlanId: 'plan-opaque' })
  useConverter.getState().show()
  expect(useConverter.getState().batchPlanId).toBe('plan-opaque')
  useConverter.getState().close()
  expect(useConverter.getState().batchPlanId).toBe('plan-opaque')
  useConverter.getState().minimize()
  expect(JSON.parse(localStorage.getItem('rw.converter')!).state).toEqual({ operationId: null, batchPlanId: 'plan-opaque', minimized: true })
})

test('choosing a source or another operation, or a new conversion, leaves the batch board', () => {
  useConverter.setState({ batchPlanId: 'plan-opaque' })
  useConverter.getState().show({ source: '/data/other' })
  expect(useConverter.getState().batchPlanId).toBeNull()
  useConverter.setState({ batchPlanId: 'plan-opaque' })
  useConverter.getState().attach('other-operation')
  expect(useConverter.getState().batchPlanId).toBeNull()
  useConverter.setState({ batchPlanId: 'plan-opaque' })
  useConverter.getState().newOperation()
  expect(useConverter.getState().batchPlanId).toBeNull()
})
