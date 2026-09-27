// UI-11 / UI-27 (AUD-A3-16, AUD-A3-23): themes are "Dark · Light · System"; the interface size
// (Compact · Default · Large) sets <html data-size> at once, Default without the attribute
import { fireEvent, render, screen, within } from '@testing-library/react'

import '../i18n'
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
