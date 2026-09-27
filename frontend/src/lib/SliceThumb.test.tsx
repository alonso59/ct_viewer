// @vitest-environment jsdom
// IMP-12 / UI-15 (AUD-A3-11, AUD-A3-12): a missing thumbnail is a muted CT-set placeholder with a
// tooltip on the inset colour (never a black square, never the "rejected" circle-slash)
import { render, screen } from '@testing-library/react'

import '../i18n'
import { SliceThumb } from './SliceThumb'

test('placeholder when there is no thumbnail', () => {
  const { container } = render(<SliceThumb pid="p" itemId={null} size={40} />)
  const thumb = container.querySelector('.thumb')
  expect(thumb).toHaveAttribute('data-empty', 'true')
  expect(screen.getByTitle(/^No thumbnail/)).toBeInTheDocument()
  expect(container.querySelector('.codicon-circle-slash')).toBeNull()
  expect(container.querySelector('svg')).not.toBeNull()
})
