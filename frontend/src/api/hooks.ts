// Server state through TanStack Query only (FE-02). Writes stamp the reviewer (FE-10).
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { requireReviewer } from '../state'
import { api, type CaseFilter } from './client'
import { keys } from './keys'
import type { Job, LabelDef, NewCurationEvent, ServerEvent, Settings } from './types'

const enabled = (...v: (string | null | undefined)[]) => v.every(Boolean)

export const useProjects = () => useQuery({ queryKey: keys.projects(), queryFn: () => api.listProjects() })
export const useProject = (pid: string) =>
  useQuery({ queryKey: keys.project(pid), queryFn: () => api.getProject(pid), enabled: enabled(pid) })
export const useCases = (pid: string, f: CaseFilter = {}) =>
  useQuery({ queryKey: keys.cases(pid, f), queryFn: () => api.listCases(pid, f), enabled: enabled(pid), placeholderData: (p) => p })
export const useCase = (pid: string, cid: string | null) =>
  useQuery({ queryKey: keys.case(pid, cid ?? ''), queryFn: () => api.getCase(pid, cid ?? ''), enabled: enabled(pid, cid) })
export const useItem = (pid: string, iid: string | null) =>
  useQuery({ queryKey: keys.item(pid, iid ?? ''), queryFn: () => api.getItem(pid, iid ?? ''), enabled: enabled(pid, iid) })
export const useWarnings = (pid: string) =>
  useQuery({ queryKey: keys.warnings(pid), queryFn: () => api.listWarnings(pid), enabled: enabled(pid) })
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
export const useJobs = () => useQuery({ queryKey: keys.jobs(), queryFn: () => api.listJobs() })
export const useSchema = () => useQuery({ queryKey: keys.schema(), queryFn: () => api.schema(), staleTime: Infinity })
export const useFsList = (path: string) => useQuery({ queryKey: keys.fs(path), queryFn: () => api.fsList(path) })
export const useImportPreview = (pid: string, root: string | null) =>
  useQuery({ queryKey: keys.preview(pid, root ?? ''), queryFn: () => api.importPreview(pid, root ?? ''), enabled: enabled(pid, root) })

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
    mutationFn: (name: string) => api.createProject(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects() }),
  })
}

export function useCommitImport(pid: string) {
  return useMutation({ mutationFn: () => api.commitImport(pid) })
}

export function useUpdateLabels(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (labels: LabelDef[]) => api.updateLabelMap(pid, labels),
    onSuccess: (p) => qc.setQueryData(keys.project(pid), p),
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
      void qc.invalidateQueries({ queryKey: keys.jobs() })
    },
  })
}

export function useCancelJob(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api.cancelJob(pid, jobId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs() }),
  })
}

function invalidateCuration(qc: QueryClient, pid: string) {
  void qc.invalidateQueries({ queryKey: ['project', pid, 'cases'] })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'case'] })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'events'] })
  void qc.invalidateQueries({ queryKey: ['project', pid, 'curation'] })
  void qc.invalidateQueries({ queryKey: keys.projects() })
}

/** API-40 stand-in: patch/invalidate caches from server events; the caller gets each event. */
export function useProjectEvents(pid: string | null, onEvent?: (e: ServerEvent) => void) {
  const qc = useQueryClient()
  useEffect(() => {
    if (!pid) return
    return api.subscribe(pid, (e) => {
      if (e.event === 'curation.appended') invalidateCuration(qc, pid)
      if (e.event === 'job.progress' || e.event === 'job.finished') {
        qc.setQueryData(keys.jobs(), (old: Job[] | undefined) => {
          const rest = (old ?? []).filter((j) => j.job_id !== e.data.job_id)
          return [e.data, ...rest]
        })
        if (e.event === 'job.finished') {
          void qc.invalidateQueries({ queryKey: keys.runs(pid) })
          void qc.invalidateQueries({ queryKey: ['project', pid, 'run'] })
        }
      }
      if (e.event === 'index.rebuilt') void qc.invalidateQueries({ queryKey: ['project', pid] })
      if (e.event === 'project.updated') void qc.invalidateQueries({ queryKey: keys.project(pid) })
      onEvent?.(e)
    })
  }, [pid, qc, onEvent])
}
