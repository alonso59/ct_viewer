// Curation decisions without UI: the shared draft and `submitDecision`, used by the (lazy) form and
// by the eager keyboard shortcuts (CUR-04, UI-12).
import { create } from 'zustand'

import i18n from '../../i18n'
import { api, keys, ProblemError, queryClient, type CurationContext, type CurationStatus, type Priority, type Project } from '../../api'
import { problemToastText } from '../../lib'
import { toast, useWorkbench } from '../../shell'
import { requireReviewer, useViewerSync } from '../../state'
import { getViewerContext } from '../../features/viewer'

// Draft shared by the left view, the inspector and the keyboard shortcuts
interface Draft {
  target: string
  priority: Priority
  comment: string
  addToQueue: boolean
  proposedSide: 'L' | 'R' | ''
  set: (p: Partial<Omit<Draft, 'set' | 'reset'>>) => void
  reset: () => void
}
/** Mask targets carry `seg_id` (CURATION §Targets) */
export const isMaskTarget = (t: string) => t === 'seg' || t === 'voi_mask' || t.startsWith('label:')

export const useDraft = create<Draft>()((set) => ({
  target: 'seg',
  priority: 'medium',
  comment: '',
  addToQueue: false,
  proposedSide: '',
  set: (p) => set(p),
  reset: () => set({ comment: '', addToQueue: false, proposedSide: '' }),
}))

/** VW-19: the set mask decisions are about: the one on screen, else the project's `default_seg` */
export function activeSegOf(pid: string): string {
  return useViewerSync.getState().shownSeg ?? queryClient.getQueryData<Project>(keys.project(pid))?.default_seg ?? 'imported'
}

/** VW-16 viewer snapshot for the audit context; the server adds fingerprints, phase and import id */
function viewerContext(): CurationContext {
  const v = getViewerContext()
  return v ? { viewer: { axis: v.axis, slice: v.slice, ww: v.ww, wl: v.wl } } : {}
}

/** Refresh derived state right after our own write (other reviewers' writes arrive via SSE) */
function refreshCuration(pid: string) {
  void queryClient.invalidateQueries({ queryKey: keys.scope(pid, 'curation') })
  void queryClient.invalidateQueries({ queryKey: keys.scope(pid, 'events') })
  void queryClient.invalidateQueries({ queryKey: keys.scope(pid, 'cases') })
  void queryClient.invalidateQueries({ queryKey: keys.projects() })
}

/** Append a decision for the active item using the current draft. Used by buttons and shortcuts. */
export async function submitDecision(status: CurationStatus, over: { addToQueue?: boolean } = {}) {
  const t = i18n.t.bind(i18n)
  const pid = useWorkbench.getState().pid
  const { activeItemId, activeCaseId, shownSeg } = useViewerSync.getState()
  const d = useDraft.getState()
  if (!pid || !activeCaseId) return
  const caseTarget = d.target === 'case' || !activeItemId
  const target = caseTarget ? 'case' : d.target
  try {
    const reviewer = await requireReviewer()
    if (!reviewer) return
    await api.appendEvent(
      pid,
      {
        item_id: caseTarget ? null : activeItemId,
        case_id: activeCaseId,
        target,
        status,
        priority: d.priority,
        comment: d.comment,
        add_to_queue: over.addToQueue ?? d.addToQueue,
        proposed_side: target === 'side' && d.proposedSide ? d.proposedSide : null,
        // ADR-0015: mask decisions name the set whose mask is on screen (VW-19); none shown → the
        // server's default_seg (AUD-A5-05: never a set the item has no mask in)
        ...(isMaskTarget(target) && shownSeg ? { seg_id: shownSeg } : {}),
        context: viewerContext(),
      },
      reviewer,
    )
    d.reset()
    refreshCuration(pid)
    toast({ message: t('curation.saved', { status: t(`status.${status}`), target, id: caseTarget ? activeCaseId : activeItemId }), tone: 'ok' })
  } catch (e) {
    const detail = e instanceof ProblemError ? problemToastText(e) : ''
    toast({ message: detail ? t('curation.saveFailedDetail', { detail }) : t('common.saveFailed'), tone: 'error' })
  }
}
