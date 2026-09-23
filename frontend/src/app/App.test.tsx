import { render, screen } from '@testing-library/react'

import '../i18n'
import { App } from './App'

test('workspace home renders with the product name and projects from the mock API', async () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Radiology Workbench' })).toBeInTheDocument()
  expect(await screen.findByText('Dataset900 (synthetic)')).toBeInTheDocument()
})
