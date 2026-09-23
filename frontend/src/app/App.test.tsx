import { render, screen } from '@testing-library/react'

import '../i18n'
import { App } from './App'

test('renders the product name from the locale file', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Radiology Workbench' })).toBeInTheDocument()
})
