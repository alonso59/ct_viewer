// Curation decisions without UI: the shared draft and `submitDecision`, used by the (lazy) form and
// by the eager keyboard shortcuts.
import { create } from 'zustand'

import i18n from '../../i18n'
import { api, keys, ProblemError, queryClient, type CurationContext, type CurationEvent, type CurationStateRow, type CurationStatus, type Priority, type Project } from '../../api'
import { fmtAgo, itemName, knownPhase, problemToastText } from '../../lib'
import { toast, useWorkbench } from '../../shell'
import { requireReviewer, useViewerSync } from '../../state'
import { getViewerContext } from '../../features/viewer'
import { isMask, rowOf, targetName } from './model'

// Draft shared by the left view, the inspector and the keyboard shortcuts. Target and priority are
// working preferences; comment, queue flag and side belong to the item they were typed for.
interface Draft {
  target: string
  priority: Priority
  comment: string
  addToQueue: boolean
  proposedSide: 'L' | 'R' | ''
  set: (p: Partial<Omit<Draft, 'set' | 'reset'>>) => void
  reset: () => void
}

export const useDraft = create<Draft>()((set) => ({
  target: 'seg',
  priority: 'medium',
  comment: '',
  addToQueue: false,
  proposedSide: '',
  set: (p) => set(p),
  reset: () => set({ comment: '', addToQueue: false, proposedSide: '' }),
}))

type ItemDraft = Pick<Draft, 'comment' | 'addToQueue' | 'proposedSide'>
const EMPTY: ItemDraft = { comment: '', addToQueue: false, proposedSide: '' }

/** Another session's decision on a target since its item was opened (from the live events) */
export interface TheirDecision { reviewer: string; status: CurationStatus; at: string }
const theirs = new Map<string, TheirDecision>()
const decisionKey = (itemId: string | null, caseId: string, target: string, seg: string | null | undefined) => `${itemId ?? caseId}|${target}|${isMask(target) ? seg ?? '' : ''}`

/** A live event from another session: writing over it asks first (Keep mine / Use theirs) */
export function noteTheirs(e: Pick<CurationEvent, 'item_id' | 'case_id' | 'target' | 'seg_id' | 'reviewer' | 'status' | 'at'>) {
  theirs.set(decisionKey(e.item_id, e.case_id, e.target, e.seg_id), { reviewer: e.reviewer, status: e.status, at: e.at })
}

/** A write held back because someone else decided the same target after the item was opened;
 *  the server still keeps the last writer once the reviewer chooses */
interface Held {
  status: CurationStatus
  over: { addToQueue?: boolean }
  key: string
  theirs: TheirDecision
}
export const useConflict = create<{ held: Held | null }>()(() => ({ held: null }))

/** Keeps each item's unsaved comment, queue flag and side with that item while the viewer moves
 *  between cases, and starts the item's "since opened" window for other reviewers' decisions;
 *  returns the unsubscribe */
export function trackActiveItem(): () => void {
  const kept = new Map<string, ItemDraft>()
  const keyOf = (s: { activeCaseId: string | null; activeItemId: string | null }) => (s.activeCaseId ? `${s.activeCaseId}|${s.activeItemId ?? ''}` : null)
  let owner = keyOf(useViewerSync.getState())
  return useViewerSync.subscribe((s) => {
    const key = keyOf(s)
    if (key === owner) return
    const { comment, addToQueue, proposedSide } = useDraft.getState()
    if (owner) {
      if (comment || addToQueue || proposedSide) kept.set(owner, { comment, addToQueue, proposedSide })
      else kept.delete(owner)
    }
    owner = key
    useDraft.setState((key && kept.get(key)) || EMPTY)
    // what is on screen now is the baseline: only later decisions by others ask first
    for (const k of [...theirs.keys()]) if (k.startsWith(`${s.activeItemId}|`) || k.startsWith(`${s.activeCaseId}|`)) theirs.delete(k)
    useConflict.setState({ held: null })
  })
}

/** Keep mine: write the held decision over theirs */
export function keepHeld() {
  const held = useConflict.getState().held
  if (held) void submitDecision(held.status, { ...held.over, keepMine: true })
}

/** Use theirs: drop the held decision and this item's draft; their decision stands */
export function dropHeld() {
  const held = useConflict.getState().held
  if (held) theirs.delete(held.key)
  useConflict.setState({ held: null })
  useDraft.getState().reset()
}

/** The set mask decisions are about: the one on screen, else the project's `default_seg` */
export function activeSegOf(pid: string): string {
  return useViewerSync.getState().shownSeg ?? queryClient.getQueryData<Project>(keys.project(pid))?.default_seg ?? 'imported'
}

/** Viewer snapshot for the audit context; the server adds fingerprints, phase and import id */
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

export async function submitDecision(status: CurationStatus, over: { addToQueue?: boolean; keepMine?: boolean } = {}) {
  const t = i18n.t.bind(i18n)
  const pid = useWorkbench.getState().pid
  const { activeItemId, activeCaseId, shownSeg } = useViewerSync.getState()
  const d = useDraft.getState()
  if (!pid || !activeCaseId) return
  const caseTarget = d.target === 'case' || !activeItemId
  const target = caseTarget ? 'case' : d.target
  const seg = isMask(target) && shownSeg ? { seg_id: shownSeg } : {}
  const before = rowOf(queryClient.getQueryData<CurationStateRow[]>(keys.curationState(pid)) ?? [], activeItemId, activeCaseId, target, activeSegOf(pid))
  const key = decisionKey(caseTarget ? null : activeItemId, activeCaseId, target, activeSegOf(pid))
  const other = theirs.get(key)
  if (other && !over.keepMine) {
    useConflict.setState({ held: { status, over: { addToQueue: over.addToQueue }, key, theirs: other } })
    // the inspector shows both choices; the toast reaches a reviewer working by keyboard
    toast({
      message: t('curation.heldToast', { reviewer: other.reviewer, status: t(`status.${other.status}`), ago: fmtAgo(other.at) }),
      tone: 'warn',
      action: { label: t('curation.keepMine'), run: keepHeld },
    })
    return
  }
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
        // Mask decisions name the set whose mask is on screen; none shown → the server's
        // default_seg, never a set the item has no mask in
        ...seg,
        context: viewerContext(),
      },
      reviewer,
    )
    d.reset()
    theirs.delete(key)
    useConflict.setState({ held: null })
    refreshCuration(pid)
    // Undo appends the previous decision again: the history keeps both events
    const undo = async () => {
      try {
        await api.appendEvent(pid, {
          item_id: caseTarget ? null : activeItemId, case_id: activeCaseId, target,
          status: before?.status ?? 'not_reviewed', priority: before?.priority ?? d.priority, comment: before?.comment ?? '',
          add_to_queue: before?.add_to_queue ?? false, proposed_side: before?.proposed_side ?? null, ...seg, context: viewerContext(),
        }, reviewer)
        refreshCuration(pid)
        toast({ message: t('curation.undone', { status: t(`status.${before?.status ?? 'not_reviewed'}`) }), tone: 'ok' })
      } catch (e) {
        toast({ message: t('curation.saveFailedDetail', { detail: problemToastText(e) }), tone: 'error' })
      }
    }
    toast({
      // names, not identifiers: "Accepted · Label: tumor · case_00042 · NP · Full scan"
      message: t('curation.saved', {
        status: t(`status.${status}`),
        target: targetName(target, queryClient.getQueryData<Project>(keys.project(pid))?.label_map ?? [], t),
        id: caseTarget || !activeItemId ? activeCaseId : itemName(activeItemId, t, knownPhase(pid, activeItemId)),
      }),
      tone: 'ok',
      action: { label: t('common.undo'), run: () => void undo() },
    })
  } catch (e) {
    const detail = e instanceof ProblemError ? problemToastText(e) : ''
    toast({ message: detail ? t('curation.saveFailedDetail', { detail }) : t('common.saveFailed'), tone: 'error' })
  }
}
