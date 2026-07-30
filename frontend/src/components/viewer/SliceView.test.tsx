import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../services/api'
import SliceView from './SliceView'

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>()
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      getSliceBlob: vi.fn(),
    },
  }
})

const mockedApi = vi.mocked(apiClient)

function renderLoadedSliceView(overrides: Partial<React.ComponentProps<typeof SliceView>> = {}) {
  const props: React.ComponentProps<typeof SliceView> = {
    accent: '#fbbf24',
    axis: 'axial',
    crosshair: { x: 0.5, y: 0.5 },
    disabled: false,
    errorText: null,
    index: 2,
    maxIndex: 5,
    onCrosshairChange: vi.fn(),
    onHandleExpired: vi.fn(),
    onSliceChange: vi.fn(),
    onWindowLevelDrag: vi.fn(),
    query: {
      load_handle: 'handle-a',
      ww: 400,
      wl: 50,
      layers: [1, 2],
      opacity_1: 0.15,
      opacity_2: 0.2,
      opacity_3: 0.15,
    },
    requestKey: 'handle-a',
    wl: 50,
    ww: 400,
    ...overrides,
  }

  const result = render(<SliceView {...props} />)
  return { ...result, props }
}

function setRect(element: Element, width = 512, height = 512) {
  vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
    bottom: height,
    height,
    left: 0,
    right: width,
    top: 0,
    width,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
}

async function loadImage(axis = 'axial', index = 2) {
  const image = await screen.findByAltText(`${axis} slice ${index + 1}`)
  Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 512 })
  Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 512 })
  fireEvent.load(image)
  return image
}

describe('SliceView PNG interaction baseline', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.getSliceBlob.mockResolvedValue(new Blob(['png'], { type: 'image/png' }))
  })

  it('requests PNG slices with the active query and scrolls through slice indices', async () => {
    const { props } = renderLoadedSliceView()
    const viewport = document.querySelector('[data-slice-viewport="axial"]')
    expect(viewport).not.toBeNull()
    setRect(viewport as Element)
    await loadImage()

    expect(mockedApi.getSliceBlob).toHaveBeenCalledWith('axial', 2, props.query, {
      signal: expect.any(AbortSignal),
    })

    fireEvent.wheel(viewport as Element, { deltaY: 100 })
    await waitFor(() => expect(props.onSliceChange).toHaveBeenCalledWith(3))
  })

  it('maps click positions through the fitted PNG image into crosshair fractions', async () => {
    const { props } = renderLoadedSliceView()
    const viewport = document.querySelector('[data-slice-viewport="axial"]') as Element
    setRect(viewport, 640, 320)
    await loadImage()

    fireEvent.click(viewport, { clientX: 320, clientY: 160 })
    expect(props.onCrosshairChange).toHaveBeenCalledWith({ x: 0.5, y: 0.5 })

    fireEvent.click(viewport, { clientX: 160, clientY: 0 })
    expect(props.onCrosshairChange).toHaveBeenLastCalledWith({ x: 0, y: 0 })
  })

  it('preserves current zoom, pan, and fit-reset interactions', async () => {
    const { props } = renderLoadedSliceView()
    const root = document.querySelector('[data-slice-root="axial"]') as Element
    const viewport = document.querySelector('[data-slice-viewport="axial"]') as Element
    setRect(viewport)
    await loadImage()

    fireEvent.wheel(viewport, { clientX: 256, clientY: 256, ctrlKey: true, deltaY: -100 })
    expect(await screen.findByText(/1\.14×/)).toBeInTheDocument()

    fireEvent.dblClick(viewport)
    await waitFor(() => expect(screen.getByText(/1\.00×/)).toBeInTheDocument())

    fireEvent.mouseDown(root, { button: 0, shiftKey: true, clientX: 100, clientY: 100 })
    fireEvent.mouseMove(window, { clientX: 130, clientY: 118 })
    fireEvent.mouseUp(window)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Fit' })).toHaveClass('MuiButton-contained'),
    )

    fireEvent.dblClick(viewport)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Fit' })).toHaveClass('MuiButton-outlined'),
    )
    expect(props.onSliceChange).not.toHaveBeenCalled()
  })

  it('preserves right-drag window/level adjustment', async () => {
    const { props } = renderLoadedSliceView()
    const root = document.querySelector('[data-slice-root="axial"]') as Element
    await loadImage()

    fireEvent.mouseDown(root, { button: 2, clientX: 30, clientY: 40 })
    fireEvent.mouseMove(window, { clientX: 45, clientY: 35 })
    fireEvent.mouseUp(window)

    expect(props.onWindowLevelDrag).toHaveBeenCalledWith(400, 50, 15, -5)
  })
})
