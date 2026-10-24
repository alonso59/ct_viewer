// @vitest-environment jsdom
// VW-14 / D31: late engine initialization cannot escape tab cleanup or hang an active viewer.
import { act, render, screen } from '@testing-library/react'

import '../../i18n'
import type { ItemRecord } from '../../api'
import { createViewer } from './engine'
import { ViewerSurface } from './ViewerSurface'
import type { ViewerHandle } from './model/types'

vi.mock('./engine', () => ({ createViewer: vi.fn(), hasWebgl2: () => true, VolumeFetchError: class extends Error {} }))
vi.mock('./Viewport', () => ({ Viewport: () => null }))
vi.mock('./Measurements', () => ({ MeasureLayer: () => null }))

const item = { item_id: 'case.01.complete.-', case_id: 'case', scan_idx: '01', scope: 'complete', modality: 'CT', geometry: null } as ItemRecord

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

function pending() {
  let reject: (reason: Error) => void = () => { throw new Error('No pending engine') }
  vi.mocked(createViewer).mockImplementation(() => new Promise((_resolve, fail) => { reject = fail }))
  return (reason: Error) => reject(reason)
}

test('a failed active engine shows recovery instead of leaving a loading veil', async () => {
  const reject = pending()
  render(<ViewerSurface item={item} imageUrl="/image" labels={[]} active loaded />)
  await act(async () => reject(new Error('error loading dynamically imported module: /private-engine-url')))
  expect(screen.getByRole('alert')).toHaveTextContent('The viewer could not start')
  expect(screen.getByRole('button', { name: 'Reload app' })).toBeInTheDocument()
  expect(screen.queryByText(/private-engine-url/)).toBeNull()
})

test('a rejected engine import after tab cleanup is handled without changing the next view', async () => {
  const reject = pending()
  const surface = render(<ViewerSurface item={item} imageUrl="/image" labels={[]} active loaded />)
  surface.unmount()
  await act(async () => reject(new Error('import aborted during navigation')))
  expect(screen.queryByRole('alert')).toBeNull()
})

test('an engine failure belongs to the tab when the selected item changes during startup', async () => {
  const reject = pending()
  const surface = render(<ViewerSurface item={item} imageUrl="/image" labels={[]} active loaded />)
  surface.rerender(<ViewerSurface item={{ ...item, item_id: 'next.01.complete.-' }} imageUrl="/next-image" labels={[]} active loaded />)
  await act(async () => reject(new Error('startup failed')))
  expect(screen.getByRole('alert')).toHaveTextContent('The viewer could not start')
})

test('an engine created after tab cleanup is disposed exactly once', async () => {
  let finish: (handle: ViewerHandle) => void = () => { throw new Error('No pending engine') }
  vi.mocked(createViewer).mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  const surface = render(<ViewerSurface item={item} imageUrl="/image" labels={[]} active loaded />)
  surface.unmount()
  const dispose = vi.fn()
  await act(async () => finish({ dispose } as unknown as ViewerHandle))
  expect(dispose).toHaveBeenCalledOnce()
})
