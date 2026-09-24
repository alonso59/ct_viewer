// Radiomics server state through TanStack Query (FE-02); writes stamp the reviewer (FE-10).
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { keys, ReviewerCancelled } from '../../api'
import { requireReviewer } from '../../state'
import { radApi } from './api'
import type { Selection, WireSettings } from './model/types'

const on = (...v: (string | null | undefined)[]) => v.every(Boolean)

export const useRadSchema = () => useQuery({ queryKey: keys.schema(), queryFn: radApi.schema, staleTime: Infinity, retry: 1 })
export const useRadProfiles = (pid: string) =>
  useQuery({ queryKey: keys.profiles(pid), queryFn: () => radApi.listProfiles(pid), enabled: on(pid) })
export const useRadRuns = (pid: string) => useQuery({ queryKey: keys.runs(pid), queryFn: () => radApi.listRuns(pid), enabled: on(pid) })
export const useRadRun = (pid: string, rid: string | null) =>
  useQuery({ queryKey: keys.run(pid, rid ?? ''), queryFn: () => radApi.getRun(pid, rid ?? ''), enabled: on(pid, rid) })
export const useRadRunErrors = (pid: string, rid: string | null) =>
  useQuery({ queryKey: keys.runErrors(pid, rid ?? ''), queryFn: () => radApi.runErrors(pid, rid ?? ''), enabled: on(pid, rid) })

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

/** Authoritative validation (API-31), debounced; `isCurrent` is false while the form is ahead of the answer */
export function useServerValidation(settings: WireSettings | null, labels: number[], nItems: number | null) {
  const body = settings ? JSON.stringify({ settings, labels, nItems }) : null
  const debounced = useDebounced(body, 300)
  const q = useQuery({
    queryKey: [...keys.schema(), 'validate', debounced ?? ''],
    queryFn: () => {
      const b = JSON.parse(debounced ?? '{}') as { settings: WireSettings; labels: number[]; nItems: number | null }
      return radApi.validate(b.settings, b.labels, b.nItems)
    },
    enabled: debounced !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  })
  return { ...q, isCurrent: debounced === body && !q.isPlaceholderData && q.isSuccess }
}

export function useEstimate(pid: string) {
  return useMutation({ mutationFn: (p: { settings: WireSettings; selection: Selection }) => radApi.estimate(pid, p.settings, p.selection) })
}

export function useSaveProfile(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { name: string; settings: WireSettings }) => radApi.saveProfile(pid, p.name, p.settings),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.profiles(pid) }),
  })
}

export function useRenameProfile(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { hash: string; name: string }) => radApi.renameProfile(pid, p.hash, p.name),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.profiles(pid) }),
  })
}

export function useDeleteProfile(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (hash: string) => radApi.deleteProfile(pid, hash),
    onSuccess: (rest) => qc.setQueryData(keys.profiles(pid), rest),
  })
}

function useRunInvalidation(pid: string) {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: keys.runs(pid) })
    void qc.invalidateQueries({ queryKey: ['project', pid, 'run'] })
    void qc.invalidateQueries({ queryKey: ['jobs'] })
  }
}

/** Starts a run (RAD-06); the Run button is the only trigger (RADIOMICS §Principles) */
export function useStartRun(pid: string) {
  const invalidate = useRunInvalidation(pid)
  return useMutation({
    mutationFn: async (body: { name: string; settings: WireSettings; selection: Selection }) => {
      const reviewer = await requireReviewer()
      if (!reviewer) throw new ReviewerCancelled()
      return radApi.startRun(pid, body, reviewer)
    },
    onSuccess: invalidate,
  })
}

export function useRunControl(pid: string) {
  const invalidate = useRunInvalidation(pid)
  return useMutation({
    mutationFn: (p: { rid: string; action: 'cancel' | 'resume' }) => (p.action === 'cancel' ? radApi.cancelRun(pid, p.rid) : radApi.resumeRun(pid, p.rid)),
    onSuccess: invalidate,
  })
}
