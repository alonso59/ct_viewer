// @vitest-environment jsdom
// UI-11 / UI-27 (AUD-A3-16, AUD-A3-23): themes are "Dark · Light · System"; the interface size
// (Compact · Default · Large) sets <html data-size> at once, Default without the attribute
import { fireEvent, render, screen, within } from '@testing-library/react'

import '../i18n'
import { registry } from '../shell'
import { useSettings } from '../state'
import { SettingsView } from './Settings'

test('theme names and interface size', () => {
  render(<SettingsView />)
  const theme = screen.getByRole('group', { name: 'Theme' })
  expect(within(theme).getAllByRole('button').map((b) => b.textContent)).toEqual(['Dark', 'Light', 'System'])
  const size = screen.getByRole('group', { name: 'Interface size' })
  expect(within(size).getByRole('button', { name: 'Default' })).toHaveAttribute('aria-pressed', 'true')
  expect(document.documentElement.dataset.size).toBeUndefined()
  fireEvent.click(within(size).getByRole('button', { name: 'Large' }))
  expect(useSettings.getState().uiSize).toBe('large')
  expect(document.documentElement.dataset.size).toBe('large')
  fireEvent.click(within(size).getByRole('button', { name: 'Compact' }))
  expect(document.documentElement.dataset.size).toBe('compact')
  fireEvent.click(within(size).getByRole('button', { name: 'Default' }))
  expect(document.documentElement.dataset.size).toBeUndefined()
})

// UI-12: the fields are labelled; a recorded key that another command uses asks first (Replace takes
// it from there, Cancel keeps both); a command without a default can get keys too
test('a key already in use asks before it is taken; any command can get keys (UI-12)', () => {
  registry.command({ id: 'test.left', title: 'cmd.toggleSidebar', keybinding: 'mod+b', run: vi.fn() })
  registry.command({ id: 'test.panel', title: 'cmd.togglePanel', keybinding: 'mod+j', run: vi.fn() })
  registry.command({ id: 'test.welcome', title: 'cmd.welcome', run: vi.fn() })
  useSettings.setState({ keybindings: {} })
  render(<SettingsView />)
  expect(screen.getByLabelText('Reviewer name')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Keybindings'), { target: { value: 'toggle panel' } })
  fireEvent.click(screen.getByRole('button', { name: 'Toggle panel: Ctrl+J' }))
  fireEvent.keyDown(screen.getByRole('textbox', { name: 'Press keys for Toggle panel' }), { key: 'b', code: 'KeyB', ctrlKey: true })
  expect(screen.getByRole('alert')).toHaveTextContent('Ctrl+B is already used by Toggle side bar')
  expect(useSettings.getState().keybindings).toEqual({})
  fireEvent.click(screen.getByRole('button', { name: 'Replace' }))
  expect(useSettings.getState().keybindings).toEqual({ 'test.left': '', 'test.panel': 'mod+b' })
  expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.change(screen.getByLabelText('Keybindings'), { target: { value: 'welcome' } })
  fireEvent.click(screen.getByRole('button', { name: 'Welcome: No keys' }))
  fireEvent.keyDown(screen.getByRole('textbox', { name: 'Press keys for Welcome' }), { key: 'u', code: 'KeyU', ctrlKey: true, altKey: true })
  expect(useSettings.getState().keybindings['test.welcome']).toBe('mod+alt+u')
})
