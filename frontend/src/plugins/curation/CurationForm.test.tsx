// @vitest-environment jsdom
// CUR-14: the curation panel shows previous and current comments from every reviewer of the case.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'

import '../../i18n'
import { api, type CurationEvent } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { CurationForm } from './CurationForm'

afterEach(() => {
  vi.restoreAllMocks()
  useWorkbench.setState({ pid: null })
  useViewerSync.setState({ activeCaseId: null, activeItemId: null })
})

test('CUR-14 the panel shows a physician and Agent GPT comment on the same target', async () => {
  const cid = 'case_00001'
  useWorkbench.setState({ pid: DEMO_PID })
  useViewerSync.setState({ activeCaseId: cid, activeItemId: cid + '.01.complete.-' })
  const event: CurationEvent = {
    case_id: cid, item_id: null, target: 'case', status: 'accepted', priority: 'medium',
    reviewer: 'Dr. AP', event_id: 'latest', at: '2026-11-20T12:00:00Z', comment: 'Human review',
    schema_version: 1, session_id: null, seg_id: null, add_to_queue: false, proposed_side: null, context: {}, source: 'ui',
  }
  const history = vi.spyOn(api, 'listEvents').mockResolvedValue([
    event,
    { ...event, event_id: 'earlier', reviewer: 'Agent GPT', comment: 'Check axial 42–50', status: 'needs_major_correction' },
  ])
  render(<QueryClientProvider client={new QueryClient()}><CurationForm /></QueryClientProvider>)
  expect(await screen.findByText('Check axial 42–50')).toBeVisible()
  expect(screen.getByText(/Agent GPT/)).toBeVisible()
  expect(screen.getByText('Human review')).toBeVisible()
  expect(screen.getByRole('option', { name: 'Whole scan' })).toBeInTheDocument()
  expect(history).toHaveBeenCalledWith(DEMO_PID, { case_id: cid })
})
