// @vitest-environment jsdom
// VW-17: ROI mean / SD are in HU on CT only; other images have no physical unit.
import { render, screen } from '@testing-library/react'

import '../../i18n'
import { useViewerSync } from '../../state'
import { MeasureLayer } from './Measurements'
import type { Measurement } from './model/measure'
import type { ViewerHandle, ViewState } from './model/types'

const handle = { canvasAt: () => [10, 10] } as unknown as ViewerHandle
const view = { planes: { axial: { index: 3 } } } as unknown as ViewState
const roi: Measurement = { id: 1, kind: 'roi', tile: 'axial', slice: 3, points: [[0, 0, 0], [1, 0, 0]], stats: { n: 9, mean: 40, sd: 2, min: 30, max: 50, areaMm2: 100 } }
const show = (value: string) => useViewerSync.setState({ activeModality: { key: 'k', value, assumed: false, component: null } })

afterEach(() => useViewerSync.setState({ activeModality: null }))

test('ROI statistics carry HU on CT and no unit on MR', () => {
  show('CT')
  const { rerender } = render(<MeasureLayer handle={handle} view={view} items={[roi]} draft={null} />)
  expect(screen.getByText('μ 40.0 σ 2.0 HU · n 9 · 1.00 cm²')).toBeInTheDocument()
  show('MR')
  rerender(<MeasureLayer handle={handle} view={view} items={[roi]} draft={null} />)
  expect(screen.getByText('μ 40.0 σ 2.0 · n 9 · 1.00 cm²')).toBeInTheDocument()
})
