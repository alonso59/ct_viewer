// Server state through TanStack Query only (FE-02). Writes stamp the reviewer (FE-10).
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { requireReviewer } from '../state'
import { api } from './client'
import { useConnection } from './connection'
import { keys } from './keys'
import type { CaseFilter } from './surface'
import type {
  CaseSummary,
  DerivedDef,
  ItemRecord,
  Job,
  LabelDef,
  NewCurationEvent,
  Preset,
  PreviewRequest,
  ServerEvent,
  Settings,
  VariablePatch,
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
export const useRun = (pid: string, rid: string) =>
  useQuery({ queryKey: keys.run(pid, rid), queryFn: () => api.getRun(pid, rid), enabled: enabled(pid, rid) })
export const useFeatures = (pid: string, rid: string | null | undefined, iid?: string | null) =>
  useQuery({
    queryKey: keys.features(pid, rid ?? '', iid ?? undefined),
    queryFn: () => api.runFeatures(pid, rid ?? '', iid ?? undefined),
    enabled: enabled(pid, rid) && iid !== null,
  })
export const useRunErrors = (pid: string, rid: string) =>
  useQuery({ queryKey: keys.runErrors(pid, rid), queryFn: () => api.runErrors(pid, rid), enabled: enabled(pid, rid) })
export const useProfiles = (pid: string) =>
  useQuery({ queryKey: keys.profiles(pid), queryFn: () => api.listProfiles(pid), enabled: enabled(pid) })
/** API-41; without a project, all jobs */
export const useJobs = (pid?: string | null) =>
  useQuery({ queryKey: keys.jobs(pid ?? undefined), queryFn: () => api.listJobs(pid ?? undefined) })
export const useSchema = () => useQuery({ queryKey: keys.schema(), queryFn: () => api.schema(), staleTime: Infinity })
export const useFsList = (path: string | null) =>
  useQuery({ queryKey: keys.fs(path), queryFn: () => api.fsList(path), placeholderData: (p) => p })

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

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { name: string; preset: Preset }) => api.createProject(p),
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

export function useUpdateLabels(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (labels: LabelDef[]) => api.updateLabelMap(pid, labels),
    onSuccess: (p) => qc.setQueryData(keys.project(pid), p),
  })
}

function invalidateVariables(qc: QueryClient, pid: string) {
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

export function useSaveProfile(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { name: string; settings: Settings }) => api.saveProfile(pid, p.name, p.settings),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.profiles(pid) }),
  })
}

export function useStartRun(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (p: { name: string; scope: 'complete' | 'voi'; labels: number[] }) => {
      const reviewer = await requireReviewer()
      if (!reviewer) throw new ReviewerCancelled()
      return api.startRun(pid, p.name, { scope: p.scope, labels: p.labels }, reviewer)
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.runs(pid) })
      void qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

export function useCancelJob(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api.cancelJob(pid, jobId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

function invalidateCuration(qc: QueryClient, pid: string) {
  void qc.invalidateQueries({ queryKey: ['project', pid, 'cases'] })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'case'] })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'events'] })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'curation'] })
  void qc.invalidateQueries({ queryKey: keys.projects() })
}

/** Apply one API-40 event to the query cache */
export function applyServerEvent(qc: QueryClient, pid: string, e: ServerEvent) {
  if (e.event === 'curation.appended') invalidateCuration(qc, pid)
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
      if (e.data.kind === 'index') void qc.invalidateQueries({ queryKey: keys.imports(pid) })
    }
  }
  if (e.event === 'index.rebuilt') {
    void qc.invalidateQueries({ queryKey: ['project', pid] })
    void qc.invalidateQueries({ queryKey: keys.projects() })
  }
  if (e.event === 'project.updated') {
    void qc.invalidateQueries({ queryKey: keys.project(pid) })
    if (e.data.fields.includes('variables')) invalidateVariables(qc, pid)
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
