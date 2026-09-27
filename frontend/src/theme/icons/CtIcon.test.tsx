// @vitest-environment jsdom
import { render } from '@testing-library/react'

import { CT_ICONS, CtIcon, type CtIconName } from './CtIcon'

// UI-15: 16 px grid, currentColor only
test.each(Object.keys(CT_ICONS) as CtIconName[])('%s follows codicon rules', (name) => {
  const { container } = render(<CtIcon name={name} />)
  const svg = container.querySelector('svg')
  expect(svg?.getAttribute('viewBox')).toBe('0 0 16 16')
  for (const p of container.querySelectorAll('path')) {
    const paint = [p.getAttribute('fill'), p.getAttribute('stroke')].filter((v) => v && v !== 'none')
    expect(paint.every((v) => v === 'currentColor')).toBe(true)
  }
})
