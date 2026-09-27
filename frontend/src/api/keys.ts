// Central query keys (FE-02)
import type { CaseFilter } from './surface'
import type { DashboardView } from './types'

/** Parts of a project that are invalidated as a whole (a prefix of the keys below) */
export type ProjectScope = 'cases' | 'case' | 'item' | 'curation' | 'events' | 'labeling' | 'run' | 'analyses'

export const keys = {
  /** Prefix of every key of one part of a project, for invalidation (AUD-A6-13) */
  scope: (pid: string, part: ProjectScope) => ['project', pid, part] as const,
  /** Prefix of every jobs key */
  allJobs: () => ['jobs'] as const,
  health: () => ['health'] as const,
  projects: (archived = false) => (archived ? (['projects', 'archived'] as const) : (['projects'] as const)),
  project: (pid: string) => ['project', pid] as const,
  roots: (pid: string) => ['project', pid, 'roots'] as const,
  cases: (pid: string, f: CaseFilter = {}) => ['project', pid, 'cases', f] as const,
  case: (pid: string, cid: string) => ['project', pid, 'case', cid] as const,
  item: (pid: string, iid: string) => ['project', pid, 'item', iid] as const,
  dicomTags: (pid: string, iid: string) => ['project', pid, 'item', iid, 'dicom-tags'] as const,
  warnings: (pid: string) => ['project', pid, 'warnings'] as const,
  imports: (pid: string) => ['project', pid, 'imports'] as const,
  variables: (pid: string) => ['project', pid, 'variables'] as const,
  brokenDerived: (pid: string) => ['project', pid, 'variables', 'broken'] as const,
  events: (pid: string, f: { item_id?: string; case_id?: string } = {}) => ['project', pid, 'events', f] as const,
  phaseEvents: (pid: string, cid: string, scan: string) => ['project', pid, 'phase', 'events', cid, scan] as const,
  curationState: (pid: string) => ['project', pid, 'curation', 'state'] as const,
  queue: (pid: string) => ['project', pid, 'curation', 'queue'] as const,
  runs: (pid: string) => ['project', pid, 'runs'] as const,
  run: (pid: string, rid: string) => ['project', pid, 'run', rid] as const,
  features: (pid: string, rid: string, iid?: string) => ['project', pid, 'run', rid, 'features', iid ?? '*'] as const,
  runErrors: (pid: string, rid: string) => ['project', pid, 'run', rid, 'errors'] as const,
  /** API-38; the body is part of the key. `['project', pid, 'run', rid, 'view']` prefixes all views of a run */
  view: (pid: string, rid: string, view: DashboardView, body: unknown) => ['project', pid, 'run', rid, 'view', view, body] as const,
  analyses: (pid: string, rid?: string) => ['project', pid, 'analyses', rid ?? '*'] as const,
  analysis: (pid: string, aid: string) => ['project', pid, 'analysis', aid] as const,
  profiles: (pid: string) => ['project', pid, 'profiles'] as const,
  jobs: (pid?: string) => ['jobs', pid ?? '*'] as const,
  schema: () => ['radiomics', 'schema'] as const,
  /** API-31; `body` is the serialized request, so equal settings share one answer */
  validation: (body: string) => ['radiomics', 'schema', 'validate', body] as const,
  fs: (path: string | null, role = 'source') => ['fs', role, path ?? ''] as const,
  /** API-07 by session id: the route names the session, never the path (AUD-A1-19) */
  open: (sid: string) => ['open', sid] as const,
  tasks: () => ['tasks'] as const,
  plugins: (pid: string | null) => ['plugins', pid] as const,
  packs: () => ['packs'] as const,
  labelTables: (pid: string) => ['project', pid, 'labeling', 'tables'] as const,
  deletedLabelTables: (pid: string) => ['project', pid, 'labeling', 'tables', 'deleted'] as const,
  labelCells: (pid: string, tid: string) => ['project', pid, 'labeling', 'cells', tid] as const,
  labelHistory: (pid: string, tid: string, target: string, col: string) => ['project', pid, 'labeling', 'history', tid, target, col] as const,
  workspaceRuns: () => ['workspace-runs'] as const,
  workspaceRun: (rid: string) => ['workspace-runs', rid] as const,
  layers: (pid: string) => ['project', pid, 'layers'] as const,
  segmentations: (pid: string) => ['project', pid, 'segmentations'] as const,
  taskRuns: (pid: string) => ['project', pid, 'task-runs'] as const,
  taskRun: (pid: string, rid: string) => ['project', pid, 'task-runs', rid] as const,
  taskRunOutputs: (pid: string, rid: string) => ['project', pid, 'task-runs', rid, 'outputs'] as const,
  taskPreflight: (pid: string, tid: string, selection: unknown) => ['project', pid, 'task-preflight', tid, selection] as const,
}
