// @vitest-environment jsdom
// VW-05 on the recorded API (TST-04): every scan row of the explorer names its modality; an item
// without one shows the project default, marked as assumed.
import * as RTooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { useMemo } from 'react'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { ProjectView } from './ProjectView'
import { useExplorer } from './store'

// Lay out all rows in jsdom; scroll geometry is verified in the browser.
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => useMemo(() => ({
    measure: () => {},
    scrollToIndex: () => {},
    getTotalSize: () => count * 22,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, size: 22, start: index * 22 })),
  }), [count]),
}))

afterEach(() => {
  useWorkbench.setState({ pid: null })
  useExplorer.setState({ filter: {}, expanded: {}, order: [] })
})

test('every scan row shows its modality badge', async () => {
  useWorkbench.setState({ pid: DEMO_PID })
  useExplorer.setState({ filter: { q: 'case_00061' }, expanded: { case_00061: true }, order: [] })
  const { items } = await api.getCase(DEMO_PID, 'case_00061')
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RTooltip.Provider>
        <ProjectView />
      </RTooltip.Provider>
    </QueryClientProvider>,
  )
  await screen.findAllByText(/^Scan \d+ · /, {}, { timeout: 3_000 })
  const rows = screen.getAllByRole('treeitem').filter((r) => r.getAttribute('aria-level') === '2')
  expect(rows).toHaveLength(items.length)
  const mr = items.find((i) => i.modality === 'MR')!
  const mrRow = rows.find((r) => r.textContent?.includes(`Scan ${mr.scan_idx} · `))!
  expect(within(mrRow).getByText('MR')).toHaveAttribute('title', 'Modality from the image metadata')
  for (const [row, item] of rows.map((r, i) => [r, items[i]!] as const)) {
    const tag = row.querySelector('.badge:not([data-phase])')
    expect(tag?.textContent).toBe(item.modality ?? 'CT (assumed)')
    if (!item.modality) expect(tag).toHaveAttribute('data-tone', 'warn')
  }
})
