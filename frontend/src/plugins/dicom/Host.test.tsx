// @vitest-environment jsdom
// U08/UI-28: reconnect the selected operation without reopening stale cached work.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render } from '@testing-library/react'
import { vi } from 'vitest'

import { api, keys, type SourceOperation } from '../../api'
import { registry } from '../../shell'
import { plugin } from './index'
import { useConverter } from './store'

vi.mock('./ConverterOverlay', () => ({ default: () => null }))
afterEach(() => useConverter.getState().close())

async function mount(selected = false) {
  useConverter.getState().close()
  const record = await api.getSourceOperation('01JSYNTHOPENBACKGROUND00000')
  const cached: SourceOperation = { ...record, status: 'running', stage: 'discovering' }
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  qc.setQueryData(keys.sourceOperations(), [cached])
  if (selected) {
    useConverter.getState().attach(record.operation_id, true)
    useConverter.setState({ open: false })
  }
  plugin.activate({ registry, revealView: () => undefined })
  const Host = registry.overlays.find((entry) => entry.id === 'dicom.converter')?.component
  if (!Host) throw new Error('Missing converter host')
  const view = render(<QueryClientProvider client={qc}><Host /></QueryClientProvider>)
  return { view, qc, record }
}

test('does not choose unselected cached running operations', async () => {
  const { view, qc } = await mount()
  expect(useConverter.getState()).toMatchObject({ open: false, operationId: null })
  view.unmount()
  qc.clear()
})

test('restores the explicitly retained ID and minimized preference', async () => {
  const { view, qc, record } = await mount(true)
  expect(useConverter.getState()).toMatchObject({ open: true, operationId: record.operation_id, minimized: true })
  view.unmount()
  qc.clear()
})

test('close stays closed even while the list still says the operation is running', async () => {
  const { view, qc } = await mount(true)
  act(() => useConverter.getState().close())
  expect(useConverter.getState()).toMatchObject({ open: false, operationId: null })
  view.unmount()
  qc.clear()
})
