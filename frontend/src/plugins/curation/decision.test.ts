// @vitest-environment jsdom
// CUR-14 / UI_SHELL keybindings: a draft stays with the item it was typed for, and a decision can be
// undone by appending the previous one again (the history keeps both events).
import '../../i18n'
import { api, keys, queryClient, type CurationStateRow } from '../../api'
import { useWorkbench } from '../../shell'
import { useReviewer, useViewerSync } from '../../state'
import { dropHeld, keepHeld, noteTheirs, submitDecision, trackActiveItem, useConflict, useDraft } from './decision'

const PID = 'P1'
const at = (caseId: string, itemId: string) => useViewerSync.setState({ activeCaseId: caseId, activeItemId: itemId })

afterEach(() => {
  vi.restoreAllMocks()
  useWorkbench.setState({ pid: null, toasts: [] })
})

test('a comment typed for one case is not sent with the next case; it comes back with its case (CUR-14)', () => {
  at('c1', 'c1.01.complete.-')
  const stop = trackActiveItem()
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

// CUR-12 (notice before overwriting): another session's decision on the same target since the item
// was opened holds the write until the reviewer writes over it or keeps theirs
test('a decision over someone else\'s recent one waits for Keep mine or Use theirs (CUR-12)', async () => {
  useWorkbench.setState({ pid: PID, toasts: [] })
  useReviewer.setState({ name: 'Dr. T' })
  at('c3', 'c3.01.complete.-')
  const stop = trackActiveItem()
  useViewerSync.setState({ shownSeg: 'imported' })
  useDraft.setState({ target: 'seg', priority: 'medium', comment: 'mine', addToQueue: false, proposedSide: '' })
  queryClient.setQueryData(keys.curationState(PID), [])
  const append = vi.spyOn(api, 'appendEvent').mockResolvedValue({} as never)
  const theirs = { item_id: 'c3.01.complete.-', case_id: 'c3', target: 'seg', seg_id: 'imported', reviewer: 'Dr. AP', at: new Date().toISOString() }
  noteTheirs({ ...theirs, status: 'rejected' })
  await submitDecision('accepted')
  expect(append).not.toHaveBeenCalled()
  expect(useConflict.getState().held).toMatchObject({ status: 'accepted', theirs: { reviewer: 'Dr. AP', status: 'rejected' } })
  expect(useWorkbench.getState().toasts.at(-1)?.message).toMatch(/^Dr\. AP set Rejected .*: your decision is not saved yet$/)
  keepHeld()
  await vi.waitFor(() => expect(append).toHaveBeenCalledTimes(1))
  await vi.waitFor(() => expect(useConflict.getState().held).toBeNull())
  // written over theirs: the next decision on the target goes through at once
  await submitDecision('rejected')
  expect(append).toHaveBeenCalledTimes(2)
  // Use theirs drops the held decision and the draft; nothing is written
  noteTheirs({ ...theirs, status: 'accepted' })
  useDraft.getState().set({ comment: 'mine again' })
  await submitDecision('needs_minor_correction')
  expect(useConflict.getState().held).not.toBeNull()
  dropHeld()
  expect(useConflict.getState().held).toBeNull()
  expect(useDraft.getState().comment).toBe('')
  expect(append).toHaveBeenCalledTimes(2)
  stop()
})
