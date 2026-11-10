// The window's work lives in this store so that minimizing it, or a route change that remounts
// the shell overlays, keeps the dry run and the conversion with their progress.
// `pid` set = the window may convert into that project.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const STEPS = ['source', 'settings', 'estimate', 'run', 'result'] as const
export type Step = (typeof STEPS)[number]
export type Target = 'project' | 'dataset'

export interface ConvSettings {
  target_profile: string
  phase_analyzer: boolean
  anonymize: 'none' | 'basic'
  name: string
  /** Folder the new dataset folder is created in */
  destination: string
}

/** A dry run in flight: `id` names it for `api.estimateProgress` */
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
  /** Into a project: add series converted by the current readers next to series from other reader versions (DCM-31) */
  allowMixedVersions: boolean
  error: unknown
  scan: Scan | null
  /** "Convert in batches" in the settings step, with the batch size and the plan previewed for these exact inputs */
  batchMode: boolean
  batchSize: number
  batchPreview: { planId: string; key: string } | null
  run: { kind: Target; rid: string } | null
}

interface ConverterState extends Draft {
  /** The batch plan the window shows as its board; it outlives the window so reopening restores it */
  batchPlanId: string | null
  open: boolean
  /** Hidden behind the running-process chip; the window keeps its state and work */
  minimized: boolean
  /** A dry run or conversion is in progress: opening again shows it instead of starting over */
  working: boolean
  /** Bumped per new window, so a fresh one starts on its first step */
  session: number
  /** A source with NIfTI instead of DICOM: "Create project from this" */
  createFrom: string | null
  show: (p?: { source?: string | null; pid?: string | null }) => void
  patch: (p: Partial<Draft>) => void
  minimize: () => void
  restore: () => void
  close: () => void
  hideForImport: (id: string) => void
  attach: (id: string, minimized?: boolean, autoOpen?: boolean) => void
  newOperation: () => void
}

export const DEFAULT_BATCH_SIZE = 40

const pad = (n: number) => String(n).padStart(2, '0')
/** The suggested dataset name; never the source folder's, which is often a patient's name */
export const defaultDatasetName = (d = new Date()) => `dataset-${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

/** The folder name the server derives from a dataset name (`workspace_runs.dataset_name`) */
export const datasetSlug = (raw: string) => raw.replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 80) || 'dataset'

const parent = (p: string) => p.replace(/\/[^/]*$/, '') || '/'

const DESTINATION_KEY = 'rw.converter.destination'
/** The last destination used in this browser, else the folder that holds the source */
export const defaultDestination = (source: string | null) => {
  try {
    const last = localStorage.getItem(DESTINATION_KEY)
    if (last) return last
  } catch { /* storage unavailable */ }
  return source ? parent(source) : ''
}
export const rememberDestination = (path: string) => {
  try { localStorage.setItem(DESTINATION_KEY, path) } catch { /* storage unavailable */ }
}

const draft = (source: string | null, pid: string | null): Draft => ({
  autoOpen: false,
  operationId: null,
  requestKey: null,
  pid,
  step: source ? 'settings' : 'source',
  browse: source ? parent(source) : null,
  source,
  target: pid ? 'project' : 'dataset',
  settings: { target_profile: 'generic', phase_analyzer: true, anonymize: 'none', name: defaultDatasetName(), destination: defaultDestination(source) },
  allowMixedVersions: false,
  error: null,
  scan: null,
  batchMode: false,
  batchSize: DEFAULT_BATCH_SIZE,
  batchPreview: null,
  run: null,
})

export const useConverter = create<ConverterState>()(persist((set) => ({
  ...draft(null, null),
  batchPlanId: null,
  open: false,
  minimized: false,
  working: false,
  session: 0,
  createFrom: null,
  show: (p) =>
    set((s) => {
      if (s.open && s.working) return { minimized: false }
      const source = p?.source ?? null
      const pid = p?.pid ?? null
      return { ...draft(source, pid), ...(source ? { batchPlanId: null } : {}), open: true, minimized: false, session: s.session + 1, createFrom: null }
    }),
  patch: (p) => set(p),
  minimize: () => set({ minimized: true }),
  restore: () => set({ minimized: false }),
  close: () => set({ ...draft(null, null), open: false, minimized: false, working: false, createFrom: null, pid: null }),
  hideForImport: (id) => set({ ...draft(null, null), operationId: id, open: false, minimized: true, working: false, createFrom: null }),
  attach: (id, minimized = false, autoOpen = false) => set((s) => ({ ...draft(null, null), batchPlanId: null, operationId: id, autoOpen, open: true, minimized, working: false, pid: null, session: s.session + 1 })),
  newOperation: () => set((s) => ({ ...draft(null, s.pid), batchPlanId: null, open: true, minimized: false, working: false, session: s.session + 1 })),
}), { name: 'rw.converter', partialize: (s) => ({ operationId: s.operationId, batchPlanId: s.batchPlanId, minimized: s.minimized }) }))
