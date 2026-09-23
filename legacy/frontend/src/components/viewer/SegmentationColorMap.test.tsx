import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import SegmentationColorMap from './SegmentationColorMap'

describe('SegmentationColorMap', () => {
  it('shows only generic cmap labels and keeps base clinical labels out of the cmap legend', () => {
    render(<SegmentationColorMap labels={[1, 2, 3, 4, 5]} />)

    expect(screen.getByText('Cmap palette')).toBeInTheDocument()
    expect(screen.getByText('Label 4')).toBeInTheDocument()
    expect(screen.getByText('#60a5fa')).toBeInTheDocument()
    expect(screen.getByText('Label 5')).toBeInTheDocument()
    expect(screen.queryByText('Kidney')).not.toBeInTheDocument()
    expect(screen.queryByText('Tumor')).not.toBeInTheDocument()
    expect(screen.queryByText('Cyst')).not.toBeInTheDocument()
  })

  it('does not render when the loaded masks only use the base labels', () => {
    const { container } = render(<SegmentationColorMap labels={[1, 2, 3]} />)

    expect(container.querySelector('[data-segmentation-cmap]')).toBeNull()
  })
})
