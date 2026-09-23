import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Axis, SliceQuery } from '../../services/api'
import MprRenderer from './MprRenderer'

vi.mock('./SliceView', () => ({
  default: ({
    axis,
    crosshair,
    disabled,
    index,
    maxIndex,
    onCrosshairChange,
    onSliceChange,
    query,
    requestKey,
    wl,
    ww,
  }: {
    axis: Axis
    crosshair: { x: number; y: number }
    disabled: boolean
    index: number
    maxIndex: number
    onCrosshairChange: (point: { x: number; y: number }) => void
    onSliceChange: (index: number) => void
    query: SliceQuery
    requestKey: string | null
    wl: number
    ww: number
  }) => (
    <button
      data-crosshair={`${crosshair.x},${crosshair.y}`}
      data-disabled={String(disabled)}
      data-layers={query.layers?.join(',') ?? ''}
      data-load-handle={requestKey ?? ''}
      data-opacities={`1:${query.opacity_1 ?? ''}|2:${query.opacity_2 ?? ''}|3:${query.opacity_3 ?? ''}`}
      data-query-handle={query.load_handle ?? ''}
      data-testid={`slice-${axis}`}
      data-wl={String(wl)}
      data-ww={String(ww)}
      onClick={() => onSliceChange(index + 1)}
      onDoubleClick={() => onCrosshairChange({ x: 0.25, y: 0.75 })}
      type="button"
    >
      {axis}:{index}/{maxIndex}
    </button>
  ),
}))

describe('MprRenderer', () => {
  it('coordinates the three PNG MPR panels while preserving the surface panel slot', () => {
    const setSlice = vi.fn()
    const setFromPanelPosition = vi.fn()
    const maxIndex: Record<Axis, number> = {
      axial: 9,
      coronal: 8,
      sagittal: 7,
    }
    const navigation = {
      crosshairPoint: { x: 1, y: 2, z: 3 },
      getCrosshair: vi.fn(() => ({ x: 0.5, y: 0.5 })),
      getMaxIndex: vi.fn((axis: Axis) => maxIndex[axis]),
      setFromPanelPosition,
      setSlice,
      sliceIndices: {
        axial: 1,
        coronal: 2,
        sagittal: 3,
      },
    }

    render(
      <MprRenderer
        errorText={null}
        navigation={navigation}
        onHandleExpired={vi.fn()}
        onWindowLevelDrag={vi.fn()}
        query={{
          load_handle: 'handle-a',
          layers: [1, 2],
          opacity_1: 0.15,
          opacity_2: 0.2,
          opacity_3: 0.15,
          wl: 50,
          ww: 400,
        }}
        requestKey="handle-a"
        surfacePanel={{
          caption: 'Surface kept',
          content: <div data-testid="surface-panel">Surface</div>,
        }}
        wl={50}
        ww={400}
      />,
    )

    expect(screen.getByText('AXIAL 2 / 10')).toBeInTheDocument()
    expect(screen.getByText('SAGITTAL 4 / 8')).toBeInTheDocument()
    expect(screen.getByText('CORONAL 3 / 9')).toBeInTheDocument()
    expect(screen.getByText('Surface kept')).toBeInTheDocument()
    expect(screen.getByTestId('surface-panel')).toBeInTheDocument()
    expect(screen.getByTestId('slice-axial')).toHaveAttribute('data-disabled', 'false')
    expect(screen.getByTestId('slice-axial')).toHaveAttribute('data-load-handle', 'handle-a')
    expect(screen.getByTestId('slice-axial')).toHaveAttribute('data-query-handle', 'handle-a')
    expect(screen.getByTestId('slice-axial')).toHaveAttribute('data-layers', '1,2')
    expect(screen.getByTestId('slice-axial')).toHaveAttribute('data-opacities', '1:0.15|2:0.2|3:0.15')
    expect(screen.getByTestId('slice-axial')).toHaveAttribute('data-ww', '400')
    expect(screen.getByTestId('slice-axial')).toHaveAttribute('data-wl', '50')
    expect(screen.getByTestId('slice-axial')).toHaveAttribute('data-crosshair', '0.5,0.5')
    expect(document.querySelector('[data-mpr-requested-renderer="png"]')).toBeInTheDocument()
    expect(document.querySelector('[data-mpr-active-renderer="png"]')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('slice-coronal'))
    expect(setSlice).toHaveBeenCalledWith('coronal', 3)

    fireEvent.doubleClick(screen.getByTestId('slice-sagittal'))
    expect(setFromPanelPosition).toHaveBeenCalledWith('sagittal', { x: 0.25, y: 0.75 })
  })

  it('disables PNG slice panels when the load handle is missing', () => {
    render(
      <MprRenderer
        errorText={null}
        navigation={navigationFixture()}
        onHandleExpired={vi.fn()}
        onWindowLevelDrag={vi.fn()}
        query={{ ww: 400, wl: 50 }}
        requestKey={null}
        surfacePanel={{
          caption: 'Surface kept',
          content: <div data-testid="surface-panel">Surface</div>,
        }}
        wl={50}
        ww={400}
      />,
    )

    expect(screen.getByTestId('slice-axial')).toHaveAttribute('data-disabled', 'true')
    expect(document.querySelector('[data-mpr-has-load-handle="false"]')).toBeInTheDocument()
    expect(document.querySelector('[data-mpr-active-renderer="png"]')).toBeInTheDocument()
  })
})

function navigationFixture() {
  const maxIndex: Record<Axis, number> = {
    axial: 9,
    coronal: 8,
    sagittal: 7,
  }
  return {
    crosshairPoint: { x: 1, y: 2, z: 3 },
    getCrosshair: vi.fn(() => ({ x: 0.5, y: 0.5 })),
    getMaxIndex: vi.fn((axis: Axis) => maxIndex[axis]),
    setFromPanelPosition: vi.fn(),
    setSlice: vi.fn(),
    sliceIndices: {
      axial: 1,
      coronal: 2,
      sagittal: 3,
    },
  }
}
