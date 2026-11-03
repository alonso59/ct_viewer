// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'

import '../../i18n'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { LayersSection, WindowSection } from './Inspector'

afterEach(() => {
  useWorkbench.setState({ pid: null, active: null })
  useViewerSync.setState({ labelVisibility: {}, segChoice: {} })
})

test('the Layers panel can show and hide every label at once', async () => {
  // Layers needs a viewer: a case tab is active
  useWorkbench.setState({ pid: DEMO_PID, active: { type: 'case', caseId: 'case_00001' } })
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

// UI-13: without a viewer, the Layers and Window/level sections are one line saying what they need
test('without a viewer the Layers and Window sections say what they need', () => {
  useWorkbench.setState({ pid: DEMO_PID, active: { type: 'welcome' } })
  render(<><LayersSection /><WindowSection /></>)
  expect(screen.getAllByText('Open a case or a file to use these controls.')).toHaveLength(2)
  expect(screen.queryByRole('checkbox')).toBeNull()
})

