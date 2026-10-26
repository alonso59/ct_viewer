// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'

import '../../i18n'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { LayersSection } from './Inspector'

afterEach(() => {
  useWorkbench.setState({ pid: null })
  useViewerSync.setState({ labelVisibility: {}, segChoice: {} })
})

test('the Layers panel can show and hide every label at once', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><LayersSection /></QueryClientProvider>)

  const all = await screen.findByRole('checkbox', { name: 'Toggle all segmentation labels' })
  expect(all).not.toBeChecked()
  fireEvent.click(all)
  expect(all).toBeChecked()
  expect(screen.getByText('Hide all labels')).toBeInTheDocument()
  fireEvent.click(all)
  expect(all).not.toBeChecked()
  expect(screen.getByText('Show all labels')).toBeInTheDocument()
})
