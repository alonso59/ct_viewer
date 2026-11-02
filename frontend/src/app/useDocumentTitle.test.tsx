// @vitest-environment jsdom
// UI_SHELL §Implementation notes (page title): the browser tab names the active tab and the
// project; Open mode names no file or folder (NFR-17).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render } from '@testing-library/react'

import '../i18n'
import { keys, type CaseDetail } from '../api'
import { registry, useWorkbench, type EditorParams } from '../shell'
import { codicon } from '../theme'
import { PageTitle, ProjectTitle } from './useDocumentTitle'

const PID = 'p1'
const ITEM = 'case_00042.01.complete.-'
registry.editor({ type: 'title-probe', component: () => null, id: () => 'title-probe', title: () => 'Settings', icon: () => codicon('file') })

afterEach(() => useWorkbench.setState({ active: null }))

function project(active: EditorParams | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(keys.case(PID, 'case_00042'), { summary: {}, items: [{ item_id: ITEM, phase: { canonical: 'NP' } }], warnings: [] } as unknown as CaseDetail)
  useWorkbench.setState({ active })
  render(
    <QueryClientProvider client={client}>
      <ProjectTitle pid={PID} name="Dataset820" />
    </QueryClientProvider>,
  )
}

test('a case tab names its item with the phase, then the project', () => {
  project({ type: 'case', caseId: 'case_00042', itemId: ITEM })
  expect(document.title).toBe('case_00042 · NP · Full scan — Dataset820 — Radiology Workbench')
})

test('another tab names itself; without a tab the project comes first', () => {
  project({ type: 'title-probe' })
  expect(document.title).toBe('Settings — Dataset820 — Radiology Workbench')
  act(() => useWorkbench.setState({ active: null }))
  expect(document.title).toBe('Dataset820 — Radiology Workbench')
})

test('Open mode names no file or folder (NFR-17); the home is the app name', () => {
  const open = render(<PageTitle titleKey="common.open" />)
  expect(document.title).toBe('Open — Radiology Workbench')
  open.unmount()
  render(<PageTitle />)
  expect(document.title).toBe('Radiology Workbench')
})
