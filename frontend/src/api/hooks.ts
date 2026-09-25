// Server state through TanStack Query only (FE-02). Writes stamp the reviewer (FE-10).
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { requireReviewer } from '../state'
import { api } from './client'
import { useConnection } from './connection'
import { keys } from './keys'
import type { CaseFilter } from './surface'
import type {
  AnalysisSpec,
  CaseSummary,
  DashboardView,
  DerivedDef,
  ItemRecord,
  Job,
  LabelDef,
  NewCurationEvent,
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
export const useProjects = () => useQuery({ queryKey: keys.projects(), queryFn: () => api.listProjects() })
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
export const useEvents = (pid: string, f: { item_id?: string; case_id?: string }) =>
  useQuery({ queryKey: keys.events(pid, f), queryFn: () => api.listEvents(pid, f), enabled: enabled(pid) })
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
/** API-38 view; the previous result stays visible while new params load. `body = null` disables it. */
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
/** API-41; without a project, all jobs */
export const useJobs = (pid?: string | null) =>
  useQuery({ queryKey: keys.jobs(pid ?? undefined), queryFn: () => api.listJobs(pid ?? undefined) })
/** API-30; the engine schema does not change while the server runs */
export const useRadiomicsSchema = () => useQuery({ queryKey: keys.schema(), queryFn: () => api.radiomicsSchema(), staleTime: Infinity, retry: 1 })
/** API-31 for one request; `body = null` disables it. The previous answer stays while a new one loads. */
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
/** API-19 (SRC-01): candidate adapters for a folder or file */
export const useDetect = () => useMutation({ mutationFn: (path: string) => api.detectSource(path) })
/** API-07: an Open-mode session for a path (SRC-09); refetching re-opens */
export const useOpenSession = (path: string | null) =>
  useQuery({ queryKey: keys.open(path ?? ''), queryFn: () => api.openPath(path ?? ''), enabled: enabled(path), staleTime: Infinity, retry: false })
export function useAttachOpen(path: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ sid, n, file }: { sid: string; n: number; file: string }) => api.attachOpen(sid, n, file),
    onSuccess: (s) => qc.setQueryData(keys.open(path), s),
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

/** API-39: create + run an analysis (ANA-01), stamped with the reviewer */
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
      void qc.invalidateQueries({ queryKey: ['project', pid, 'analyses'] })
    },
  })
}

/** API-53 (CUR-10) */
export function useCurationExports(pid: string) {
  return useMutation({ mutationFn: () => api.curationExports(pid) })
}

/** API-54 (CUR-13) */
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
    mutationFn: (p: { name: string; default_modality?: ProjectModality }) => api.createProject(p),
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

/** API-06 import (PRJ-09) */
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

/** The ETag of the project version on screen (PRJ-15): a write based on it fails with 412 if
 *  someone else changed the settings since. */
const shownEtag = (qc: QueryClient, pid: string) => qc.getQueryData<Project>(keys.project(pid))?.etag ?? ''

export function useUpdateLabels(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (labels: LabelDef[]) => api.updateLabelMap(pid, labels, shownEtag(qc, pid)),
    onSuccess: (p) => qc.setQueryData(keys.project(pid), p),
  })
}

/** API-03 settings write (UI-23): `etag` = the version the form was loaded from */
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

export const useWorkspaceRun = (rid: string | null) =>
  useQuery({
    queryKey: keys.workspaceRun(rid ?? ''),
    queryFn: () => api.getWorkspaceRun(rid ?? ''),
    enabled: !!rid,
    refetchInterval: (q) => (q.state.data && !['queued', 'running'].includes(q.state.data.status) ? false : 800),
  })
export const useLayers = (pid: string) => useQuery({ queryKey: keys.layers(pid), queryFn: () => api.listLayers(pid), enabled: enabled(pid) })
export const useLabelTables = (pid: string) =>
  useQuery({ queryKey: keys.labelTables(pid), queryFn: () => api.listLabelTables(pid), enabled: enabled(pid) })
/** LBL-10: deleted tables, for Restore */
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
      void qc.invalidateQueries({ queryKey: ['project', pid] })
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
  void qc.invalidateQueries({ queryKey: ['project', pid, 'cases'] })
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

// ---- radiomics writes (API-32..35) ---------------------------------------------------------------
/** API-32; saving settings that match a profile returns that profile */
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

/** API-33 (RAD-11) */
export function useEstimate(pid: string) {
  return useMutation({ mutationFn: (p: { settings: RadiomicsSettings; selection: Selection }) => api.estimate(pid, p.settings, p.selection) })
}

function invalidateRuns(qc: QueryClient, pid: string) {
  void qc.invalidateQueries({ queryKey: keys.runs(pid) })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'run'] })
  void qc.invalidateQueries({ queryKey: ['jobs'] })
}

/** API-34 (RAD-06), stamped with the reviewer; the Run button is the only trigger (RADIOMICS §Principles) */
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

/** API-35 cancel / resume (RAD-06/08) */
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

/** Dashboard views of every run (colour/filter by curation status or variables) */
const isViewKey = (k: readonly unknown[]) => k[0] === 'project' && k[2] === 'run' && k[4] === 'view'

function invalidateViews(qc: QueryClient, pid: string) {
  void qc.invalidateQueries({ predicate: (q) => isViewKey(q.queryKey) && q.queryKey[1] === pid })
}

function invalidateCuration(qc: QueryClient, pid: string) {
  invalidateViews(qc, pid)
  void qc.invalidateQueries({ queryKey: ['project', pid, 'cases'] })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'case'] })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'events'] })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'curation'] })
  void qc.invalidateQueries({ queryKey: keys.projects() })
}

/** The derived CUR-08 row of one event, replacing the row of the same (item, target) */
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
    proposed_phase: ev.proposed_phase ?? null,
    proposed_side: ev.proposed_side ?? null,
  }
  const same = (r: CurationStateRow) => r.item_id === row.item_id && r.case_id === row.case_id && r.target === row.target
  return rows.some((r) => r.event_id === row.event_id) ? rows : [...rows.filter((r) => !same(r)), row]
}

/** Apply one API-40 event to the query cache */
export function applyServerEvent(qc: QueryClient, pid: string, e: ServerEvent) {
  // LBL-05: other reviewers' cell edits (or a large batch announced as project.updated)
  if (e.event === 'labeling.appended' || (e.event === 'project.updated' && e.data.fields.includes('labeling')))
    void qc.invalidateQueries({ queryKey: ['project', pid, 'labeling'] })
  if (e.event === 'curation.appended') {
    // CUR-11: show the decision at once from the event (server order = last-writer-wins, CUR-12);
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
    if (!known || e.event === 'job.finished') void qc.invalidateQueries({ queryKey: ['jobs'] })
    if (e.event === 'job.finished') {
      if (e.data.kind === 'radiomics') {
        void qc.invalidateQueries({ queryKey: keys.runs(pid) })
        void qc.invalidateQueries({ queryKey: ['project', pid, 'run'] })
      }
      if (e.data.kind === 'thumbnail') useConnection.getState().bumpThumbs()
      // TSK-09: a finished task run may have registered a segmentation set, annotations or an import
      if (e.data.kind === 'task') {
        void qc.invalidateQueries({ queryKey: keys.taskRuns(pid) })
        void qc.invalidateQueries({ queryKey: keys.segmentations(pid) })
        void qc.invalidateQueries({ queryKey: ['project', pid, 'case'] })
        void qc.invalidateQueries({ queryKey: ['project', pid, 'item'] })
      }
      if (e.data.kind === 'index') void qc.invalidateQueries({ queryKey: keys.imports(pid) })
      // API-15 results are `image.sha256` / `mask.sha256` on item records
      if (e.data.kind === 'hash') {
        void qc.invalidateQueries({ queryKey: ['project', pid, 'item'] })
        void qc.invalidateQueries({ queryKey: ['project', pid, 'case'] })
      }
    }
  }
  if (e.event === 'job.status') {
    // TSK-06: `waiting_for_runner` ↔ `running`
    qc.setQueryData(keys.jobs(pid), (old: Job[] | undefined) => old?.map((j) => (j.job_id === e.data.job_id ? { ...j, status: e.data.status } : j)))
    void qc.invalidateQueries({ queryKey: keys.taskRuns(pid) })
  }
  if (e.event === 'index.rebuilt') {
    void qc.invalidateQueries({ queryKey: ['project', pid] })
    void qc.invalidateQueries({ queryKey: keys.projects() })
  }
  if (e.event === 'project.updated') {
    void qc.invalidateQueries({ queryKey: keys.project(pid) })
    if (e.data.fields.includes('variables')) invalidateVariables(qc, pid)
    // Bulk curation imports (> 500 events) publish one `project.updated` instead of per-event SSE
    if (e.data.fields.includes('curation')) invalidateCuration(qc, pid)
  }
}

/** API-40 listener for side effects (toasts, output log). Cache sync is `useProjectSync`. */
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

// ---- P7b: tasks (API-42..47) and segmentation sets (API-27) --------------------------------------
export const usePlugins = (pid: string | null) =>
  useQuery({ queryKey: keys.plugins(pid), queryFn: () => api.listPlugins(pid ?? undefined), staleTime: 15_000 })
export const useTasks = () => useQuery({ queryKey: keys.tasks(), queryFn: () => api.listTasks(), staleTime: 30_000 })
export const useSegmentations = (pid: string) =>
  useQuery({ queryKey: keys.segmentations(pid), queryFn: () => api.listSegmentations(pid), enabled: enabled(pid) })
export const useTaskRuns = (pid: string) =>
  useQuery({ queryKey: keys.taskRuns(pid), queryFn: () => api.listTaskRuns(pid), enabled: enabled(pid) })
export const useTaskRun = (pid: string, rid: string | null) =>
  useQuery({ queryKey: keys.taskRun(pid, rid ?? ''), queryFn: () => api.getTaskRun(pid, rid ?? ''), enabled: enabled(pid, rid) })
