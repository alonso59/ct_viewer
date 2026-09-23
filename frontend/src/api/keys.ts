// Central query keys (FE-02)
import type { CaseFilter } from './surface'

export const keys = {
  health: () => ['health'] as const,
  projects: () => ['projects'] as const,
  project: (pid: string) => ['project', pid] as const,
  roots: (pid: string) => ['project', pid, 'roots'] as const,
  cases: (pid: string, f: CaseFilter = {}) => ['project', pid, 'cases', f] as const,
  case: (pid: string, cid: string) => ['project', pid, 'case', cid] as const,
  item: (pid: string, iid: string) => ['project', pid, 'item', iid] as const,
  warnings: (pid: string) => ['project', pid, 'warnings'] as const,
  imports: (pid: string) => ['project', pid, 'imports'] as const,
  variables: (pid: string) => ['project', pid, 'variables'] as const,
  events: (pid: string, f: { item_id?: string; case_id?: string } = {}) => ['project', pid, 'events', f] as const,
  curationState: (pid: string) => ['project', pid, 'curation', 'state'] as const,
  queue: (pid: string) => ['project', pid, 'curation', 'queue'] as const,
  runs: (pid: string) => ['project', pid, 'runs'] as const,
  run: (pid: string, rid: string) => ['project', pid, 'run', rid] as const,
  features: (pid: string, rid: string, iid?: string) => ['project', pid, 'run', rid, 'features', iid ?? '*'] as const,
  runErrors: (pid: string, rid: string) => ['project', pid, 'run', rid, 'errors'] as const,
  profiles: (pid: string) => ['project', pid, 'profiles'] as const,
  jobs: (pid?: string) => ['jobs', pid ?? '*'] as const,
  schema: () => ['radiomics', 'schema'] as const,
  fs: (path: string | null) => ['fs', path ?? ''] as const,
}
