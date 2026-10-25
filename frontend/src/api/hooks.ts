import { isCancelledError, keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query'
import { useEffect } from 'react'

import { requireReviewer } from '../state'
import { api } from './client'
import { useConnection } from './connection'
import { keys } from './keys'
import { isTaskRunPending } from './taskStatus'
import type { CaseFilter } from './surface'
import type {
  AnalysisSpec,
  CaseSummary,
  DashboardView,
  DerivedDef,
  ItemRecord,
  Job,
  NewCurationEvent,
  NewPhaseEvent,
  CurationEvent,
  CurationStateRow,
  Project,
  ProjectModality,
  ProjectPatch,
  PreviewRequest,
  RootRole,
  RadiomicsSettings,
  Selection,
  ServerEvent,
  StartRunBody,
  VariablePatch,
  ViewRequest,
} from './types'

const enabled = (...v: (string | null | undefined)[]) => v.every(Boolean)

export const useHealth = () => useQuery({ queryKey: keys.health(), queryFn: () => api.health(), staleTime: Infinity })
export const useProjects = (archived = false) => useQuery({ queryKey: keys.projects(archived), queryFn: () => api.listProjects({ archived }) })

export function useArchiveProject() {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: keys.projects() })
  return {
    archive: useMutation({ mutationFn: (pid: string) => api.archiveProject(pid), onSuccess: done }),
    restore: useMutation({ mutationFn: (pid: string) => api.unarchiveProject(pid), onSuccess: done }),
  }
}
export const useProject = (pid: string) =>
  useQuery({ queryKey: keys.project(pid), queryFn: () => api.getProject(pid), enabled: enabled(pid) })
export const useRoots = (pid: string | null) =>
  useQuery({ queryKey: keys.roots(pid ?? ''), queryFn: () => api.listRoots(pid ?? ''), enabled: enabled(pid) })
export const useCases = (pid: string, f: CaseFilter = {}) =>
  useQuery({ queryKey: keys.cases(pid, f), queryFn: () => api.listCases(pid, f), enabled: enabled(pid), placeholderData: (p) => p })
export const useCase = (pid: string, cid: string | null) =>
  useQuery({ queryKey: keys.case(pid, cid ?? ''), queryFn: () => api.getCase(pid, cid ?? ''), enabled: enabled(pid, cid) })
export const useItem = (pid: string, iid: string | null) =>
  useQuery({ queryKey: keys.item(pid, iid ?? ''), queryFn: () => api.getItem(pid, iid ?? ''), enabled: enabled(pid, iid) })
export const useWarnings = (pid: string) =>
  useQuery({ queryKey: keys.warnings(pid), queryFn: () => api.listWarnings(pid), enabled: enabled(pid) })
export const useImportHistory = (pid: string) =>
  useQuery({ queryKey: keys.imports(pid), queryFn: () => api.importHistory(pid), enabled: enabled(pid) })
export const useVariables = (pid: string) =>
  useQuery({ queryKey: keys.variables(pid), queryFn: () => api.listVariables(pid), enabled: enabled(pid) })
export const useBrokenDerived = (pid: string) =>
  useQuery({ queryKey: keys.brokenDerived(pid), queryFn: () => api.brokenDerived(pid), enabled: enabled(pid) })
export const useEvents = (pid: string, f: { item_id?: string; case_id?: string }) =>
  useQuery({ queryKey: keys.events(pid, f), queryFn: () => api.listEvents(pid, f), enabled: enabled(pid) })
/** Phase selections of one scan, newest first */
export const usePhaseEvents = (pid: string, cid: string | null, scan: string | null) =>
  useQuery({ queryKey: keys.phaseEvents(pid, cid ?? '', scan ?? ''), queryFn: () => api.phaseEvents(pid, { case_id: cid ?? '', scan_idx: scan ?? '' }), enabled: enabled(pid, cid, scan) })
export const useCurationState = (pid: string) =>
  useQuery({ queryKey: keys.curationState(pid), queryFn: () => api.curationState(pid), enabled: enabled(pid) })
export const useQueue = (pid: string) =>
  useQuery({ queryKey: keys.queue(pid), queryFn: () => api.queue(pid), enabled: enabled(pid) })
export const useRuns = (pid: string) =>
  useQuery({ queryKey: keys.runs(pid), queryFn: () => api.listRuns(pid), enabled: enabled(pid) })
export const useRun = (pid: string, rid: string | null) =>
  useQuery({ queryKey: keys.run(pid, rid ?? ''), queryFn: () => api.getRun(pid, rid ?? ''), enabled: enabled(pid, rid) })
export const useFeatures = (pid: string, rid: string | null | undefined, iid?: string | null) =>
  useQuery({
    // `iid = null` (no active item) is disabled and must not share the whole-run key
    queryKey: iid === null ? keys.features(pid, rid ?? '', '-') : keys.features(pid, rid ?? '', iid),
    queryFn: () => api.runFeatures(pid, rid ?? '', iid ?? undefined),
    enabled: enabled(pid, rid) && iid !== null,
  })
export const useRunErrors = (pid: string, rid: string | null) =>
  useQuery({ queryKey: keys.runErrors(pid, rid ?? ''), queryFn: () => api.runErrors(pid, rid ?? ''), enabled: enabled(pid, rid) })
/** The previous result stays visible while new params load. `body = null` disables it. */
export const useDashboardView = <V extends DashboardView>(pid: string, rid: string, view: V, body: ViewRequest<V> | null) =>
  useQuery({
    queryKey: keys.view(pid, rid, view, body),
    queryFn: () => api.dashboardView(pid, rid, view, body as ViewRequest<V>),
    enabled: enabled(pid, rid) && body !== null,
    placeholderData: (p) => p,
    staleTime: 30_000,
  })
export const useAnalyses = (pid: string, rid?: string) =>
  useQuery({ queryKey: keys.analyses(pid, rid), queryFn: () => api.listAnalyses(pid, rid), enabled: enabled(pid) })
export const useAnalysis = (pid: string, aid: string | null) =>
  useQuery({ queryKey: keys.analysis(pid, aid ?? ''), queryFn: () => api.getAnalysis(pid, aid ?? ''), enabled: enabled(pid, aid), staleTime: Infinity })
export const useProfiles = (pid: string) =>
  useQuery({ queryKey: keys.profiles(pid), queryFn: () => api.listProfiles(pid), enabled: enabled(pid) })
/** Without a project, all jobs */
export const useJobs = (pid?: string | null) =>
  useQuery({ queryKey: keys.jobs(pid ?? undefined), queryFn: () => api.listJobs(pid ?? undefined) })
/** The engine schema does not change while the server runs */
export const useRadiomicsSchema = () => useQuery({ queryKey: keys.schema(), queryFn: () => api.radiomicsSchema(), staleTime: Infinity, retry: 1 })
/** `body = null` disables it. The previous answer stays while a new one loads. */
export function useRadiomicsValidation(body: { settings: RadiomicsSettings; labels: number[] | null; nItems: number | null } | null) {
  const key = body ? JSON.stringify(body) : ''
  return useQuery({
    queryKey: keys.validation(key),
    queryFn: () => api.validateRadiomics(body?.settings ?? {}, body?.labels ?? null, body?.nItems ?? null),
    enabled: body !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  })
}
export const useFsList = (path: string | null, role: RootRole = 'source') =>
  useQuery({ queryKey: keys.fs(path, role), queryFn: () => api.fsList(path, role), placeholderData: (p) => p })
/** Server-owned opening of a file or folder */
export const useStartOpen = () => useMutation({
  mutationFn: ({ path, key }: { path: string; key: string }) => api.startSourceOperation({ path, purpose: 'open', prepare_plan: false, idempotency_key: key }),
})
/** `not-found` once the session is closed or after a server restart */
export const useOpenSession = (sid: string | null) =>
  useQuery({ queryKey: keys.open(sid ?? ''), queryFn: () => api.getOpen(sid ?? ''), enabled: enabled(sid), staleTime: Infinity, retry: false })
export const useOpenItems = (sid: string | null, cursor: string | undefined, limit: number) =>
  useQuery({ queryKey: keys.openItems(sid ?? '', cursor, limit), queryFn: () => api.openItems(sid ?? '', { cursor, limit }), enabled: enabled(sid), staleTime: Infinity, retry: false, placeholderData: keepPreviousData })
export const useOpenSelection = (sid: string | null, n: number | null) =>
  useQuery({ queryKey: keys.openSelection(sid ?? '', n), queryFn: () => api.getOpen(sid ?? '', n ?? undefined), enabled: enabled(sid) && n != null, staleTime: Infinity, retry: false })
export function useAttachOpen(sid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ n, file }: { n: number; file: string }) => api.attachOpen(sid, n, file),
    onSuccess: (s, { n }) => {
      qc.setQueryData(keys.open(sid), s)
      void qc.invalidateQueries({ queryKey: keys.openSelection(sid, n) })
    },
  })
}

/** Complete item that represents a case in lists: the summary's, else derived from the case detail */
export function pickThumbItem(items: ItemRecord[], priority: string[] = ['NP', 'CMP', 'NC', 'EP', 'UNK']): ItemRecord | null {
  const ok = items.filter((i) => i.scope === 'complete' && i.status === 'active' && i.image)
  const rank = (i: ItemRecord) => {
    const k = priority.indexOf(i.phase.canonical)
    return k < 0 ? priority.length : k
  }
  return [...ok].sort((a, b) => rank(a) - rank(b))[0] ?? null
}
export function useThumbItemId(pid: string, c: Pick<CaseSummary, 'case_id' | 'thumb_item_id'> | null): string | null {
  const detail = useCase(pid, c && !c.thumb_item_id ? c.case_id : null)
  if (!c) return null
  return c.thumb_item_id ?? (detail.data ? (pickThumbItem(detail.data.items)?.item_id ?? null) : null)
}

export class ReviewerCancelled extends Error {}

export function useAppendEvent(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (ev: NewCurationEvent) => {
      const reviewer = await requireReviewer()
      if (!reviewer) throw new ReviewerCancelled()
      return api.appendEvent(pid, ev, reviewer)
    },
    onSuccess: () => invalidateCuration(qc, pid),
  })
}

export function useAppendPhase(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (ev: NewPhaseEvent) => {
      const reviewer = await requireReviewer()
      if (!reviewer) throw new ReviewerCancelled()
      return api.appendPhase(pid, ev, reviewer)
    },
    onSuccess: () => invalidatePhase(qc, pid),
  })
}

/** `fetchQuery` for commands: a live-sync refresh can cancel the fetch it joined (`refreshQueries`),
 *  so a cancelled fetch is retried instead of silently dropping the command */
export async function fetchSettled<T>(qc: QueryClient, queryKey: QueryKey, queryFn: () => Promise<T>): Promise<T> {
  for (let i = 0; ; i++) {
    try {
      return await qc.fetchQuery({ queryKey, queryFn })
    } catch (e) {
      if (!isCancelledError(e) || i >= 3) throw e
    }
  }
}

/** `useAppendPhase` outside a component (a palette command) */
export async function appendPhaseNow(qc: QueryClient, pid: string, ev: NewPhaseEvent) {
  const reviewer = await requireReviewer()
  if (!reviewer) throw new ReviewerCancelled()
  const r = await api.appendPhase(pid, ev, reviewer)
  invalidatePhase(qc, pid)
  return r
}

/** Creates and runs an analysis */
export function useCreateAnalysis(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (spec: AnalysisSpec) => {
      const reviewer = await requireReviewer()
      if (!reviewer) throw new ReviewerCancelled()
      return api.createAnalysis(pid, spec, reviewer)
    },
    onSuccess: (a) => {
      qc.setQueryData(keys.analysis(pid, a.analysis_id), a)
      void qc.invalidateQueries({ queryKey: keys.scope(pid, 'analyses') })
    },
  })
}

export function useCurationExports(pid: string) {
  return useMutation({ mutationFn: () => api.curationExports(pid) })
}

export function useImportV2(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const reviewer = await requireReviewer()
      if (!reviewer) throw new ReviewerCancelled()
      return api.importV2(pid, file, reviewer)
    },
    onSuccess: () => invalidateCuration(qc, pid),
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { name: string; default_modality?: ProjectModality; dataset_root?: string }) => api.createProject(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects() }),
  })
}

export function useRelink(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { alias: string; path: string }) => api.relinkRoot(pid, p.alias, p.path),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.project(pid) })
      void qc.invalidateQueries({ queryKey: keys.projects() })
    },
  })
}

export function useImportBundle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.importBundle(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects() }),
  })
}

export function useImportPreview(pid: string) {
  return useMutation({ mutationFn: (req: PreviewRequest) => api.importPreview(pid, req) })
}

export function useCommitImport(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (previewId: string) => api.commitImport(pid, previewId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.jobs(pid) })
      void qc.invalidateQueries({ queryKey: keys.imports(pid) })
    },
  })
}

/** The ETag of the project version on screen: a write based on it fails with 412 if
 *  someone else changed the settings since. */
const shownEtag = (qc: QueryClient, pid: string) => qc.getQueryData<Project>(keys.project(pid))?.etag ?? ''

/** `etag` = the version the form was loaded from */
export function useUpdateProject(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ patch, etag }: { patch: ProjectPatch; etag?: string }) => api.updateProject(pid, patch, etag ?? shownEtag(qc, pid)),
    onSuccess: (p) => {
      qc.setQueryData(keys.project(pid), p)
      void qc.invalidateQueries({ queryKey: keys.projects() })
    },
  })
}

/** Workspace task runs, newest first (the converted datasets on the home) */
export const useWorkspaceRuns = () => useQuery({ queryKey: keys.workspaceRuns(), queryFn: () => api.listWorkspaceRuns() })
export const useSourceOperations = (on = true) => useQuery({ queryKey: keys.sourceOperations(), queryFn: () => api.listSourceOperations(), enabled: on, refetchInterval: 3000 })
export const useSourceOperation = (id: string | null) => useQuery({
  queryKey: keys.sourceOperation(id ?? ''), queryFn: () => api.getSourceOperation(id ?? ''), enabled: !!id,
  refetchInterval: (q) => isTaskRunPending(q.state.data?.status) || isTaskRunPending(q.state.data?.phase_run?.status) ? 800 : false,
})
export const useSourceDetection = (id: string | null) => useQuery({
  queryKey: keys.sourceDetection(id ?? ''), queryFn: () => api.sourceOperationDetection(id ?? ''), enabled: !!id,
})
export const useSourcePlan = (id: string | null, attempt: number | null, cursor?: string, action?: 'convert' | 'skip') => useQuery({
  queryKey: keys.sourcePlan(id ?? '', attempt, cursor, action),
  queryFn: () => api.sourceOperationPlan(id ?? '', { cursor, action }), enabled: !!id && attempt !== null,
})
export const useWorkspaceRun = (rid: string | null) =>
  useQuery({
    queryKey: keys.workspaceRun(rid ?? ''),
    queryFn: () => api.getWorkspaceRun(rid ?? ''),
    enabled: !!rid,
    refetchInterval: (q) => (isTaskRunPending(q.state.data?.status) ? 800 : false),
  })
/** A named dry run's stage while it runs; `not-found` before it starts and after it returned */
export const useEstimateProgress = (eid: string | null) =>
  useQuery({ queryKey: keys.estimateProgress(eid ?? ''), queryFn: () => api.estimateProgress(eid ?? ''), enabled: !!eid, retry: false, refetchInterval: 500 })
export const useLayers = (pid: string) => useQuery({ queryKey: keys.layers(pid), queryFn: () => api.listLayers(pid), enabled: enabled(pid) })
export const useLabelTables = (pid: string) =>
  useQuery({ queryKey: keys.labelTables(pid), queryFn: () => api.listLabelTables(pid), enabled: enabled(pid) })
/** Deleted tables, for Restore */
export const useDeletedLabelTables = (pid: string) =>
  useQuery({ queryKey: keys.deletedLabelTables(pid), queryFn: () => api.listLabelTables(pid, true), enabled: enabled(pid) })
export const useLabelCells = (pid: string, tid: string) =>
  useQuery({ queryKey: keys.labelCells(pid, tid), queryFn: () => api.labelCells(pid, tid), enabled: enabled(pid, tid) })
export const useLabelHistory = (pid: string, tid: string, target: string | null, col: string | null) =>
  useQuery({
    queryKey: keys.labelHistory(pid, tid, target ?? '', col ?? ''),
    queryFn: () => api.labelHistory(pid, tid, target ?? undefined, col ?? undefined),
    enabled: enabled(pid, tid) && !!target && !!col,
  })
export const usePacks = () => useQuery({ queryKey: keys.packs(), queryFn: () => api.listPacks(), staleTime: 60_000 })

export function useApplyPack(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (packId: string) => api.applyPack(pid, packId),
    onSuccess: (r) => {
      qc.setQueryData(keys.project(pid), r.project)
      void qc.invalidateQueries({ queryKey: keys.project(pid) })
    },
  })
}

export function useViewToken(pid: string) {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: keys.project(pid) })
  return {
    create: useMutation({ mutationFn: () => api.createViewToken(pid), onSuccess: done }),
    revoke: useMutation({ mutationFn: () => api.revokeViewToken(pid), onSuccess: done }),
  }
}

function invalidateVariables(qc: QueryClient, pid: string) {
  invalidateViews(qc, pid)
  void qc.invalidateQueries({ queryKey: keys.variables(pid) })
  void qc.invalidateQueries({ queryKey: keys.scope(pid, 'cases') })
}

export function usePatchVariable(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { name: string; patch: VariablePatch }) => api.patchVariable(pid, p.name, p.patch),
    onSuccess: () => invalidateVariables(qc, pid),
  })
}
export function useCreateDerived(pid: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (def: DerivedDef) => api.createDerived(pid, def), onSuccess: () => invalidateVariables(qc, pid) })
}
export function useDeleteDerived(pid: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (name: string) => api.deleteDerived(pid, name), onSuccess: () => invalidateVariables(qc, pid) })
}
export function useImportExternal(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { file: File; key: 'case_id' | 'patient_id' }) => api.importExternal(pid, p.file, p.key),
    onSuccess: () => invalidateVariables(qc, pid),
  })
}

/** Saving settings that match a profile returns that profile */
export function useSaveProfile(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { name: string; settings: RadiomicsSettings }) => api.saveProfile(pid, p.name, p.settings),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.profiles(pid) }),
  })
}

export function useRenameProfile(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { hash: string; name: string }) => api.renameProfile(pid, p.hash, p.name),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.profiles(pid) }),
  })
}

export function useDeleteProfile(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (hash: string) => api.deleteProfile(pid, hash),
    onSuccess: (rest) => qc.setQueryData(keys.profiles(pid), rest),
  })
}

export function useEstimate(pid: string) {
  return useMutation({ mutationFn: (p: { settings: RadiomicsSettings; selection: Selection }) => api.estimate(pid, p.settings, p.selection) })
}

function invalidateRuns(qc: QueryClient, pid: string) {
  void qc.invalidateQueries({ queryKey: keys.runs(pid) })
  void qc.invalidateQueries({ queryKey: keys.scope(pid, 'run') })
  void qc.invalidateQueries({ queryKey: keys.allJobs() })
}

export function useStartRun(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: StartRunBody) => {
      const reviewer = await requireReviewer()
      if (!reviewer) throw new ReviewerCancelled()
      return api.startRun(pid, body, reviewer)
    },
    onSuccess: () => invalidateRuns(qc, pid),
  })
}

export function useRunControl(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { rid: string; action: 'cancel' | 'resume' }) => (p.action === 'cancel' ? api.cancelRun(pid, p.rid) : api.resumeRun(pid, p.rid)),
    onSuccess: () => invalidateRuns(qc, pid),
  })
}

export function useCancelJob(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api.cancelJob(pid, jobId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.allJobs() }),
  })
}

/** Dashboard views of every run (colour/filter by curation status or variables) */
const isViewKey = (k: readonly unknown[]) => k[0] === 'project' && k[2] === 'run' && k[4] === 'view'

function invalidateViews(qc: QueryClient, pid: string) {
  void qc.invalidateQueries({ predicate: (q) => isViewKey(q.queryKey) && q.queryKey[1] === pid })
}

/** The effective phase shows in cases, items, filters, variables and dashboard views */
function invalidatePhase(qc: QueryClient, pid: string) {
  invalidateViews(qc, pid)
  for (const k of ['cases', 'case', 'item', 'phase', 'variables'] as const) void refreshQueries(qc, ['project', pid, k])
}

/** Invalidate like `invalidateQueries`, but also restart a *first* fetch that is still running:
 *  TanStack joins an in-flight fetch of a query without data instead of starting a new one, so
 *  an event that arrives during the first load would be lost. */
export function refreshQueries(qc: QueryClient, queryKey: readonly unknown[]) {
  for (const q of qc.getQueryCache().findAll({ queryKey }))
    // silent = "a new fetch follows" (as TanStack's own cancelRefetch); only active queries refetch
    if (q.state.data === undefined && q.state.fetchStatus === 'fetching' && q.isActive()) void q.cancel({ silent: true })
  return qc.invalidateQueries({ queryKey })
}

function invalidateCuration(qc: QueryClient, pid: string) {
  invalidateViews(qc, pid)
  for (const k of ['cases', 'case', 'events', 'curation'] as const) void refreshQueries(qc, ['project', pid, k])
  void refreshQueries(qc, keys.projects())
}

/** Mask targets carry a segmentation set; an event without one means `imported` */
const segKey = (target: string, seg: string | null | undefined) =>
  target === 'seg' || target === 'voi_mask' || target.startsWith('label:') ? (seg ?? 'imported') : null

/** The derived curation-state row of one event, replacing the row of the same (item, target, seg_id) */
export function upsertStateRow(rows: CurationStateRow[], ev: CurationEvent): CurationStateRow[] {
  const row: CurationStateRow = {
    item_id: ev.item_id ?? null,
    case_id: ev.case_id,
    target: ev.target,
    status: ev.status,
    priority: ev.priority,
    comment: ev.comment ?? '',
    reviewer: ev.reviewer,
    at: ev.at,
    event_id: ev.event_id,
    add_to_queue: ev.add_to_queue ?? false,
    proposed_side: ev.proposed_side ?? null,
    seg_id: segKey(ev.target, ev.seg_id),
  }
  const same = (r: CurationStateRow) =>
    r.item_id === row.item_id && r.case_id === row.case_id && r.target === row.target && segKey(r.target, r.seg_id) === row.seg_id
  return rows.some((r) => r.event_id === row.event_id) ? rows : [...rows.filter((r) => !same(r)), row]
}

export function applyServerEvent(qc: QueryClient, pid: string, e: ServerEvent) {
  // Other reviewers' cell edits (or a large batch announced as project.updated)
  if (e.event === 'labeling.appended' || (e.event === 'project.updated' && e.data.fields.includes('labeling')))
    void refreshQueries(qc, ['project', pid, 'labeling'])
  // A selection here or in another browser (imports announce `project.updated` with `phase`)
  if (e.event === 'phase.appended' || (e.event === 'project.updated' && e.data.fields.includes('phase'))) invalidatePhase(qc, pid)
  if (e.event === 'curation.appended') {
    // Show the decision at once from the event (server order = last-writer-wins);
    // the refetch below confirms it, but can queue behind other requests on a busy server
    qc.setQueryData<CurationStateRow[]>(keys.curationState(pid), (old) => (old ? upsertStateRow(old, e.data) : old))
    invalidateCuration(qc, pid)
  }
  if (e.event === 'job.progress' || e.event === 'job.finished') {
    let known = false
    qc.setQueryData(keys.jobs(pid), (old: Job[] | undefined) =>
      old?.map((j) => {
        if (j.job_id !== e.data.job_id) return j
        known = true
        return e.event === 'job.progress'
          ? { ...j, ...e.data, status: j.status === 'queued' ? 'running' : j.status }
          : { ...j, ...e.data, finished_at: new Date().toISOString() }
      }),
    )
    if (!known || e.event === 'job.finished') void qc.invalidateQueries({ queryKey: keys.allJobs() })
    if (e.event === 'job.finished') {
      if (e.data.kind === 'radiomics') {
        void qc.invalidateQueries({ queryKey: keys.runs(pid) })
        void qc.invalidateQueries({ queryKey: keys.scope(pid, 'run') })
      }
      if (e.data.kind === 'thumbnail') useConnection.getState().bumpThumbs()
      // A finished task run may have registered a segmentation set, annotations or an import
      if (e.data.kind === 'task') {
        void qc.invalidateQueries({ queryKey: keys.taskRuns(pid) })
        void qc.invalidateQueries({ queryKey: keys.segmentations(pid) })
        void qc.invalidateQueries({ queryKey: keys.scope(pid, 'case') })
        void qc.invalidateQueries({ queryKey: keys.scope(pid, 'item') })
      }
      if (e.data.kind === 'index') void qc.invalidateQueries({ queryKey: keys.imports(pid) })
      // Hash results are `image.sha256` / `mask.sha256` on item records
      if (e.data.kind === 'hash') {
        void qc.invalidateQueries({ queryKey: keys.scope(pid, 'item') })
        void qc.invalidateQueries({ queryKey: keys.scope(pid, 'case') })
      }
    }
  }
  if (e.event === 'job.status') {
    // `waiting_for_runner` ↔ `running`
    qc.setQueryData(keys.jobs(pid), (old: Job[] | undefined) => old?.map((j) => (j.job_id === e.data.job_id ? { ...j, status: e.data.status } : j)))
    void qc.invalidateQueries({ queryKey: keys.taskRuns(pid) })
  }
  // Events were missed (server replay gap, or the stream reopened after an error)
  if (e.event === 'reset') {
    void refreshQueries(qc, ['project', pid])
    void refreshQueries(qc, keys.projects())
    void qc.invalidateQueries({ queryKey: keys.allJobs() })
  }
  if (e.event === 'index.rebuilt') {
    void qc.invalidateQueries({ queryKey: keys.project(pid) })
    void qc.invalidateQueries({ queryKey: keys.projects() })
  }
  if (e.event === 'project.updated' && e.data.fields.includes('recycle')) {
    void refreshQueries(qc, keys.project(pid))
    void refreshQueries(qc, keys.projects())
  }
  if (e.event === 'project.updated') {
    void qc.invalidateQueries({ queryKey: keys.project(pid) })
    if (e.data.fields.includes('variables')) invalidateVariables(qc, pid)
    // Bulk curation imports (> 500 events) publish one `project.updated` instead of per-event SSE
    if (e.data.fields.includes('curation')) invalidateCuration(qc, pid)
  }
}

/** Event-stream listener for side effects (toasts, output log). Cache sync is `useProjectSync`. */
export function useProjectEvents(pid: string | null, onEvent?: (e: ServerEvent) => void) {
  useEffect(() => {
    if (!pid || !onEvent) return
    return api.subscribe(pid, onEvent)
  }, [pid, onEvent])
}

/** Cache sync + connection state for the open project; mount once (ProjectRoute) */
export function useProjectSync(pid: string | null) {
  const qc = useQueryClient()
  useEffect(() => {
    if (!pid) return
    const setState = useConnection.getState().set
    return api.subscribe(pid, (e) => applyServerEvent(qc, pid, e), setState)
  }, [pid, qc])
}

export const usePlugins = (pid: string | null) =>
  useQuery({ queryKey: keys.plugins(pid), queryFn: () => api.listPlugins(pid ?? undefined), staleTime: 15_000 })
export const useTasks = () => useQuery({ queryKey: keys.tasks(), queryFn: () => api.listTasks(), staleTime: 30_000 })
export const useSegmentations = (pid: string) =>
  useQuery({ queryKey: keys.segmentations(pid), queryFn: () => api.listSegmentations(pid), enabled: enabled(pid) })
/** Polls while a supervised run waits for its verified cleanup: no job event announces it */
const STOPPING_RUN: readonly string[] = ['pausing', 'cancelling', 'reconciling', 'cleanup_pending']
export const useTaskRuns = (pid: string) =>
  useQuery({
    queryKey: keys.taskRuns(pid),
    queryFn: () => api.listTaskRuns(pid),
    enabled: enabled(pid),
    refetchInterval: (q) => (q.state.data?.some((r) => STOPPING_RUN.includes(r.status)) ? 2000 : false),
  })
/** Archived supervised runs, fetched only when asked */
export const useArchivedTaskRuns = (pid: string, on: boolean) =>
  useQuery({ queryKey: keys.archivedTaskRuns(pid), queryFn: () => api.listTaskRuns(pid, undefined, true), enabled: on && enabled(pid) })
export const useTaskRun = (pid: string, rid: string | null) =>
  useQuery({ queryKey: keys.taskRun(pid, rid ?? ''), queryFn: () => api.getTaskRun(pid, rid ?? ''), enabled: enabled(pid, rid), refetchInterval: (q) => q.state.data?.task.id === 'dicom.convert' && isTaskRunPending(q.state.data.status) ? 800 : false })

/** Recycle the whole scan only after a preview and explicit confirmation. */
export function useRecycleScan(pid: string, iid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (token: string) => {
      const reviewer = await requireReviewer()
      if (!reviewer) throw new ReviewerCancelled()
      return api.recycleScan(pid, iid, token, reviewer)
    },
    onSuccess: () => {
      void refreshQueries(qc, keys.project(pid))
      void refreshQueries(qc, keys.projects())
    },
  })
}
