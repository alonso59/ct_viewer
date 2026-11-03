// @vitest-environment jsdom
// CUR-14 / UI_SHELL keybindings: a draft stays with the item it was typed for, and a decision can be
// undone by appending the previous one again (the history keeps both events).
import '../../i18n'
import { api, keys, queryClient, type CurationStateRow } from '../../api'
import { useWorkbench } from '../../shell'
import { useReviewer, useViewerSync } from '../../state'
import { submitDecision, trackDraftOwner, useDraft } from './decision'

const PID = 'P1'
const at = (caseId: string, itemId: string) => useViewerSync.setState({ activeCaseId: caseId, activeItemId: itemId })

afterEach(() => {
  vi.restoreAllMocks()
  useWorkbench.setState({ pid: null, toasts: [] })
})

test('a comment typed for one case is not sent with the next case; it comes back with its case (CUR-14)', () => {
  at('c1', 'c1.01.complete.-')
  const stop = trackDraftOwner()
  useDraft.getState().set({ comment: 'Leak at the upper pole', addToQueue: true })
  at('c2', 'c2.01.complete.-')
  expect(useDraft.getState()).toMatchObject({ comment: '', addToQueue: false })
  at('c1', 'c1.01.complete.-')
  expect(useDraft.getState()).toMatchObject({ comment: 'Leak at the upper pole', addToQueue: true })
  stop()
})

test('Undo appends the previous decision for the same item and target (CUR-14)', async () => {
  useWorkbench.setState({ pid: PID, toasts: [] })
  useReviewer.setState({ name: 'Dr. T' })
  useViewerSync.setState({ activeCaseId: 'c1', activeItemId: 'c1.01.complete.-', shownSeg: 'imported' })
  useDraft.setState({ target: 'seg', priority: 'medium', comment: '', addToQueue: false, proposedSide: '' })
  const before: CurationStateRow = {
    item_id: 'c1.01.complete.-', case_id: 'c1', target: 'seg', status: 'needs_minor_correction', priority: 'high', comment: 'Leak',
    reviewer: 'A', at: '2026-11-01T10:00:00Z', event_id: 'e1', add_to_queue: true, proposed_side: null, seg_id: 'imported',
  }
  queryClient.setQueryData(keys.curationState(PID), [before])
  const append = vi.spyOn(api, 'appendEvent').mockResolvedValue({} as never)
  await submitDecision('accepted')
  expect(append).toHaveBeenLastCalledWith(PID, expect.objectContaining({ status: 'accepted', target: 'seg' }), 'Dr. T')
  const saved = useWorkbench.getState().toasts.at(-1)!
  expect(saved.action?.label).toBe('Undo')
  saved.action!.run()
  await vi.waitFor(() => expect(append).toHaveBeenCalledTimes(2))
  expect(append).toHaveBeenLastCalledWith(PID, expect.objectContaining({
    item_id: 'c1.01.complete.-', target: 'seg', status: 'needs_minor_correction', priority: 'high', comment: 'Leak', add_to_queue: true, seg_id: 'imported',
  }), 'Dr. T')
})
