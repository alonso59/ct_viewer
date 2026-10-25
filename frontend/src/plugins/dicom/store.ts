// Converter overlay state (UI-25): opened from Welcome, Open mode on DICOM, the Library and a
// project's Data tab. `pid` set = the window may convert into that project (DCM-14).
// The window's work lives here, not in the component: minimizing it, or a route change that
// remounts the shell overlays, keeps the dry run and the conversion (and their progress).
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { TaskEstimate } from '../../api'

export const STEPS = ['source', 'settings', 'estimate', 'run', 'result'] as const
export type Step = (typeof STEPS)[number]
export type Target = 'project' | 'dataset'

export interface ConvSettings {
  target_profile: string
  phase_analyzer: boolean
  anonymize: 'none' | 'basic'
  name: string
}

/** A dry run in flight: `id` names it for `api.estimateProgress` (DCM-06) */
export interface Scan {
  id: string
  started: number
}

export interface Draft {
  autoOpen: boolean
  operationId: string | null
  requestKey: string | null
  pid: string | null
  step: Step
  browse: string | null
  source: string | null
  target: Target
  settings: ConvSettings
  estimate: TaskEstimate | null
  error: unknown
  scan: Scan | null
  run: { kind: Target; rid: string } | null
}

interface ConverterState extends Draft {
  open: boolean
  /** Hidden behind the running-process chip; the window keeps its state and work (UI-25) */
  minimized: boolean
  /** A dry run or conversion is in progress: opening again shows it instead of starting over */
  working: boolean
  /** Bumped per new window, so a fresh one starts on its first step */
  session: number
  /** A source with NIfTI instead of DICOM: "Create project from this" (AUD-A2-07) */
  createFrom: string | null
  show: (p?: { source?: string | null; pid?: string | null }) => void
  patch: (p: Partial<Draft>) => void
  minimize: () => void
  restore: () => void
  close: () => void
  attach: (id: string, minimized?: boolean, autoOpen?: boolean) => void
  newOperation: () => void
}

const pad = (n: number) => String(n).padStart(2, '0')
/** AUD-A5-16 (NFR-17): the suggested dataset name; never the source folder's (often a patient) name */
export const defaultDatasetName = (d = new Date()) => `dataset-${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

/** The folder name the server derives from a dataset name (`workspace_runs.dataset_name`) */
export const datasetSlug = (raw: string) => raw.replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 80) || 'dataset'

const parent = (p: string) => p.replace(/\/[^/]*$/, '') || '/'

const draft = (source: string | null, pid: string | null): Draft => ({
  autoOpen: false,
  operationId: null,
  requestKey: null,
  pid,
  step: source ? 'settings' : 'source',
  browse: source ? parent(source) : null,
  source,
  target: pid ? 'project' : 'dataset',
  settings: { target_profile: 'generic', phase_analyzer: true, anonymize: 'none', name: defaultDatasetName() },
  estimate: null,
  error: null,
  scan: null,
  run: null,
})

export const useConverter = create<ConverterState>()(persist((set) => ({
  ...draft(null, null),
  open: false,
  minimized: false,
  working: false,
  session: 0,
  pid: null,
  createFrom: null,
  show: (p) =>
    set((s) => {
      if (s.open && s.working) return { minimized: false }
      const source = p?.source ?? null
      const pid = p?.pid ?? null
      return { ...draft(source, pid), open: true, minimized: false, session: s.session + 1, pid, createFrom: null }
    }),
  patch: (p) => set(p),
  minimize: () => set({ minimized: true }),
  restore: () => set({ minimized: false }),
  close: () => set({ ...draft(null, null), open: false, minimized: false, working: false, createFrom: null, pid: null }),
  attach: (id, minimized = false, autoOpen = false) => set((s) => ({ ...draft(null, null), operationId: id, autoOpen, open: true, minimized, working: false, pid: null, session: s.session + 1 })),
  newOperation: () => set((s) => ({ ...draft(null, s.pid), open: true, minimized: false, working: false, session: s.session + 1 })),
}), { name: 'rw.converter', partialize: (s) => ({ operationId: s.operationId, minimized: s.minimized }) }))
