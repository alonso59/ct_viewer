// @vitest-environment jsdom
// COH-01: the case row's menu offers "Show in Cohort"; it focuses the case in the Cohort grid.
import * as RTooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { useMemo } from 'react'
import { vi } from 'vitest'

import '../../i18n'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { registerCohort } from '../cohort'
import { EMPTY_FILTERS, useCohort } from '../cohort/store'
import { ProjectView } from './ProjectView'
import { useExplorer } from './store'

// Lay out all rows in jsdom; scroll geometry is verified in the browser
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => useMemo(() => ({
    measure: () => {},
    scrollToIndex: () => {},
    getTotalSize: () => count * 24,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, key: index, size: 24, start: index * 24 })),
  }), [count]),
}))

registerCohort()

test('the case row menu shows the case in the Cohort grid', async () => {
  // the command is scoped to a project route
  window.history.pushState({}, '', `/p/${DEMO_PID}`)
  useWorkbench.setState({ pid: DEMO_PID })
  useExplorer.setState({ pid: null, byProject: {}, filter: {}, expanded: {}, order: [] })
  useCohort.setState({ pid: null, byProject: {}, focusCase: null, group: null, pinned: [], expanded: {}, filters: EMPTY_FILTERS })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RTooltip.Provider>
        <ProjectView />
      </RTooltip.Provider>
    </QueryClientProvider>,
  )
  const row = (await screen.findAllByRole('treeitem'))[0]!
  const caseId = row.querySelector('.mono')?.textContent
  expect(caseId).toBeTruthy()
  fireEvent.contextMenu(row)
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Show in Cohort' }))
  expect(useCohort.getState().focusCase).toBe(caseId)
})
