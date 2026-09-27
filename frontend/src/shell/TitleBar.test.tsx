// ADR-0028 (UI-01, UI-13): one "Layout" menu replaces VS Code's three title-bar toggles; its items
// are check items with the unchanged shortcuts
import { fireEvent, render, screen } from '@testing-library/react'

import '../i18n'
import { useLayout } from '../state'
import { TitleBar } from './TitleBar'
import { ShellProviders } from './Workbench'

test('layout menu instead of three toggles', async () => {
  useLayout.getState().load('p-title')
  render(<ShellProviders><TitleBar brand={null} /></ShellProviders>)
  expect(screen.queryByRole('button', { name: /Toggle (side bar|panel|inspector)/ })).toBeNull()
  fireEvent.keyDown(screen.getByRole('button', { name: /^Layout/ }), { key: 'Enter' })
  const inspector = await screen.findByRole('menuitemcheckbox', { name: /Inspector/ })
  expect(inspector).toHaveAttribute('aria-checked', 'false')
  expect(screen.getByRole('menuitemcheckbox', { name: /Side bar/ })).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(inspector)
  expect(useLayout.getState().inspectorVisible).toBe(true)
})
