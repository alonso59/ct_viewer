// Settings tab on the in-memory mock (VITE_API_MODE=mock, the unit-test default): the engine schema,
// seeded profile and server validation come from the mock, so the tab opens instead of "engine not available".
import * as RTooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'

import '../../i18n'
import { API_MODE } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { SettingsEditor } from './SettingsEditor'

test('settings tab works against the mock API', async () => {
  expect(API_MODE).toBe('mock')
  useWorkbench.setState({ pid: DEMO_PID })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RTooltip.Provider>
        <SettingsEditor />
      </RTooltip.Provider>
    </QueryClientProvider>,
  )
  expect(await screen.findByRole('navigation', { name: 'Setting groups' }, { timeout: 3_000 })).toBeInTheDocument()
  expect(await screen.findByText('Settings are valid', {}, { timeout: 3_000 })).toBeInTheDocument()
  expect(screen.queryByText('The radiomics engine is not available')).not.toBeInTheDocument()
  expect(await screen.findByRole('option', { name: /Engine defaults/ }, { timeout: 3_000 })).toBeInTheDocument()
})
