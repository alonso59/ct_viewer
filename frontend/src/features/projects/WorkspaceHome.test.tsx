// @vitest-environment jsdom
// UI-04, UI-17: the home groups its entries by level (View files, Projects); an empty workspace has
// exactly one primary action, and its empty Recent offers buttons.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import '../../i18n'
import { keys, type ProjectSummary } from '../../api'
import { WorkspaceHome } from './WorkspaceHome'

function home(projects: ProjectSummary[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.projects(false), projects)
  return render(<MemoryRouter><QueryClientProvider client={qc}><WorkspaceHome /></QueryClientProvider></MemoryRouter>)
}

test('an empty workspace: two groups, New project… is the one primary action, Recent offers buttons', () => {
  const { container } = home([])
  const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
  expect(headings.slice(0, 2)).toEqual(['View files', 'Projects'])
  const primary = container.querySelectorAll('.home-action-primary, .btn-primary')
  expect(primary).toHaveLength(1)
  expect(primary[0]).toHaveTextContent('New project…')
  const empty = screen.getByText('No projects yet.').closest('.empty') as HTMLElement
  expect(within(empty).getByRole('button', { name: 'New project…' })).toBeInTheDocument()
  expect(within(empty).getByRole('button', { name: 'Open file or folder…' })).toBeInTheDocument()
})

test('with a project, no entry is primary', () => {
  const { container } = home([{ project_id: 'p1', name: 'Dataset900', created_at: '2026-01-01T00:00:00Z', last_opened_at: null, archived: false, n_cases: 3, n_cases_excluded: 0, curation_progress: 0 } as unknown as ProjectSummary])
  expect(container.querySelectorAll('.home-action-primary')).toHaveLength(0)
})
