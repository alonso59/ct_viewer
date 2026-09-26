import { render, screen } from '@testing-library/react'

import '../i18n'
import { App } from './App'

test('workspace home renders with the product name and projects from the mock API', async () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Radiology Workbench' })).toBeInTheDocument()
  expect(await screen.findByText('Dataset900 (synthetic)')).toBeInTheDocument()
})

// AUD-A1-01 / AUD-A2-09 (UI-05): the palette opens on the home, lists the home's commands, and
// a New project dialog blocks it (no palette over a modal)
test('the command palette works on the workspace home', async () => {
  const { fireEvent } = await import('@testing-library/react')
  const { useWorkbench } = await import('../shell')
  // cmdk measures its list; jsdom has neither API
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Element.prototype.scrollIntoView ??= () => {}
  useWorkbench.setState({ palette: null })
  render(<App />)
  await screen.findByText('Dataset900 (synthetic)')
  fireEvent.keyDown(window, { code: 'KeyP', key: 'P', ctrlKey: true, shiftKey: true })
  const palette = await screen.findByRole('dialog')
  expect(await screen.findByRole('option', { name: /New project/ })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: /About/ })).toBeInTheDocument()
  expect(screen.queryByRole('option', { name: /Next case/ })).toBeNull()
  fireEvent.keyDown(palette, { key: 'Escape', code: 'Escape' })
  expect(useWorkbench.getState().palette).toBeNull()
  // A modal is up: Ctrl+Shift+P does nothing
  fireEvent.click(screen.getByRole('button', { name: /New project/ }))
  await screen.findByRole('dialog', { name: 'New project' })
  fireEvent.keyDown(window, { code: 'KeyP', key: 'P', ctrlKey: true, shiftKey: true })
  expect(useWorkbench.getState().palette).toBeNull()
})
