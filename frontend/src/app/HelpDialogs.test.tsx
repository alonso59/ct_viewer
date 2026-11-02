// @vitest-environment jsdom
// UI_SHELL §Commands (Help), FE-08: Keyboard shortcuts shows one group per menu name, a filter by
// title or keys, a list the keyboard can scroll, and commands named as actions.
import { fireEvent, render, screen, within } from '@testing-library/react'

import '../i18n'
import '../i18n/lazy'
import { bootstrap } from './bootstrap'
import { useHelp } from './help'
import HelpDialogs from './HelpDialogs'

beforeAll(() => bootstrap())
afterEach(() => useHelp.setState({ open: null }))

test('one View group, a focusable list and action names; the filter matches titles and keys', () => {
  useHelp.setState({ open: 'keys' })
  render(<HelpDialogs />)
  const list = screen.getByRole('region', { name: 'Shortcuts' })
  expect(list).toHaveAttribute('tabindex', '0')
  expect(within(list).getAllByRole('heading', { name: 'View', level: 3 })).toHaveLength(1)
  expect(within(list).getByText('Mark accepted')).toBeInTheDocument()
  const filter = screen.getByRole('searchbox', { name: 'Filter shortcuts' })
  fireEvent.change(filter, { target: { value: 'F6' } })
  expect(within(list).getByText('Focus next region')).toBeInTheDocument()
  expect(within(list).queryByText('Mark accepted')).toBeNull()
  fireEvent.change(filter, { target: { value: 'mark rej' } })
  expect(within(list).getByText('Mark rejected')).toBeInTheDocument()
  fireEvent.change(filter, { target: { value: 'zzz' } })
  expect(within(list).getByText('No shortcut matches')).toBeInTheDocument()
})
