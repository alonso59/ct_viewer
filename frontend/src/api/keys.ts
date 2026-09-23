// Central query keys (FE-02)
import type { CaseFilter } from './client'

export const keys = {
  projects: () => ['projects'] as const,
  project: (pid: string) => ['project', pid] as const,
  cases: (pid: string, f: CaseFilter = {}) => ['project', pid, 'cases', f] as const,
  case: (pid: string, cid: string) => ['project', pid, 'case', cid] as const,
  item: (pid: string, iid: string) => ['project', pid, 'item', iid] as const,
  warnings: (pid: string) => ['project', pid, 'warnings'] as const,
  events: (pid: string, f: { item_id?: string; case_id?: string } = {}) => ['project', pid, 'events', f] as const,
  curationState: (pid: string) => ['project', pid, 'curation', 'state'] as const,
  queue: (pid: string) => ['project', pid, 'curation', 'queue'] as const,
  runs: (pid: string) => ['project', pid, 'runs'] as const,
  run: (pid: string, rid: string) => ['project', pid, 'run', rid] as const,
  features: (pid: string, rid: string, iid?: string) => ['project', pid, 'run', rid, 'features', iid ?? '*'] as const,
  runErrors: (pid: string, rid: string) => ['project', pid, 'run', rid, 'errors'] as const,
  profiles: (pid: string) => ['project', pid, 'profiles'] as const,
  jobs: () => ['jobs'] as const,
  schema: () => ['radiomics', 'schema'] as const,
  fs: (path: string) => ['fs', path] as const,
  preview: (pid: string, root: string) => ['project', pid, 'import-preview', root] as const,
}
