// @vitest-environment jsdom
// UI-05: a command that is disabled now but says why stays listed, dimmed, with its reason; one
// without a reason stays hidden.
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import '../i18n'
import { CommandPalette } from './CommandPalette'
import { registry } from './registry'
import { useWorkbench } from './workbenchStore'

test('disabled commands with a reason are listed dimmed and cannot run (UI-05)', () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  Element.prototype.scrollIntoView ??= () => {}
  const run = vi.fn()
  registry.command({ id: 'test.reasoned', title: 'status.accepted', enabled: () => false, disabledReason: () => 'reason.openCase', run })
  registry.command({ id: 'test.hidden', title: 'status.rejected', enabled: () => false, run })
  useWorkbench.setState({ palette: 'commands' })
  render(<MemoryRouter initialEntries={['/p/P1']}><CommandPalette /></MemoryRouter>)
  const item = screen.getByRole('option', { name: /Accepted/ })
  expect(item).toHaveAttribute('aria-disabled', 'true')
  expect(item).toHaveTextContent('Open a case first')
  expect(screen.queryByRole('option', { name: /Rejected/ })).toBeNull()
})
