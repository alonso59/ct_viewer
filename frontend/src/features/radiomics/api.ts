// Radiomics HTTP calls (API-30..37) typed from the generated schema (FE-03). They live in the
// feature until the shared `Api` surface adopts the real wire shapes (LANE_NOTES, P5-FE).
import createClient from 'openapi-fetch'

import { ProblemError } from '../../api'
import type { paths } from '../../api/schema'
import type {
  EstimateResult,
  Profile,
  RunDetail,
  RunError,
  RunSummary,
  Selection,
  SettingsSchema,
  ValidateResult,
  WireSettings,
} from './model/types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
const client = createClient<paths>({ baseUrl: BASE })

type Res<T> = { data?: T; error?: unknown; response: Response }

function problem(status: number, body: unknown, fallback: string): ProblemError {
  const p = (body && typeof body === 'object' ? body : {}) as { type?: unknown; title?: unknown; detail?: unknown }
  const slug = typeof p.type === 'string' ? (p.type.split('/').filter(Boolean).at(-1) ?? 'about:blank') : 'about:blank'
  return new ProblemError(status, slug, typeof p.title === 'string' ? p.title : fallback, typeof p.detail === 'string' ? p.detail : undefined)
}

async function unwrap<T>(p: Promise<Res<T>>): Promise<T> {
  const { data, error, response } = await p
  if (!response.ok) throw problem(response.status, error, response.statusText)
  return data as T
}

async function allPages<T>(get: (cursor: string | undefined) => Promise<{ items: T[]; next_cursor?: string | null }>): Promise<T[]> {
  const out: T[] = []
  let cursor: string | undefined
  for (;;) {
    const page = await get(cursor)
    out.push(...page.items)
    if (!page.next_cursor) return out
    cursor = page.next_cursor
  }
}

const path = (pid: string) => ({ path: { pid } })
const LIMIT = 500

export const radApi = {
  schema: (): Promise<SettingsSchema> => unwrap(client.GET('/api/v1/radiomics/schema')),
  validate: (settings: WireSettings, labels: number[] | null, nItems: number | null): Promise<ValidateResult> =>
    unwrap(client.POST('/api/v1/radiomics/validate', { body: { settings, labels, n_items: nItems } })),
  listProfiles: (pid: string): Promise<Profile[]> =>
    allPages((cursor) => unwrap(client.GET('/api/v1/projects/{pid}/radiomics/profiles', { params: { ...path(pid), query: { limit: LIMIT, cursor } } }))),
  saveProfile: (pid: string, name: string, settings: WireSettings): Promise<Profile> =>
    unwrap(client.POST('/api/v1/projects/{pid}/radiomics/profiles', { params: path(pid), body: { name, settings } })),
  renameProfile: (pid: string, hash: string, name: string): Promise<Profile> =>
    unwrap(client.PATCH('/api/v1/projects/{pid}/radiomics/profiles/{phash}', { params: { path: { pid, phash: hash } }, body: { name } })),
  deleteProfile: (pid: string, hash: string): Promise<Profile[]> =>
    unwrap(client.DELETE('/api/v1/projects/{pid}/radiomics/profiles/{phash}', { params: { path: { pid, phash: hash }, query: { limit: LIMIT } } })).then((p) => p.items),
  estimate: (pid: string, settings: WireSettings, selection: Selection): Promise<EstimateResult> =>
    unwrap(client.POST('/api/v1/projects/{pid}/radiomics/estimate', { params: path(pid), body: { settings, selection } })),
  listRuns: (pid: string): Promise<RunSummary[]> =>
    allPages((cursor) => unwrap(client.GET('/api/v1/projects/{pid}/radiomics/runs', { params: { ...path(pid), query: { limit: LIMIT, cursor } } }))),
  getRun: (pid: string, rid: string): Promise<RunDetail> =>
    unwrap(client.GET('/api/v1/projects/{pid}/radiomics/runs/{rid}', { params: { path: { pid, rid } } })),
  startRun: (pid: string, body: { name: string; settings: WireSettings; selection: Selection }, reviewer: string): Promise<RunDetail> =>
    unwrap(client.POST('/api/v1/projects/{pid}/radiomics/runs', { params: { ...path(pid), header: { 'x-reviewer': reviewer } }, body })),
  cancelRun: (pid: string, rid: string): Promise<RunDetail> =>
    unwrap(client.POST('/api/v1/projects/{pid}/radiomics/runs/{rid}/cancel', { params: { path: { pid, rid } } })),
  resumeRun: (pid: string, rid: string): Promise<RunDetail> =>
    unwrap(client.POST('/api/v1/projects/{pid}/radiomics/runs/{rid}/resume', { params: { path: { pid, rid } } })),
  runErrors: (pid: string, rid: string): Promise<RunError[]> =>
    allPages((cursor) => unwrap(client.GET('/api/v1/projects/{pid}/radiomics/runs/{rid}/errors', { params: { path: { pid, rid }, query: { limit: LIMIT, cursor } } }))),
  /** API-36 CSV/Parquet download URL (RAD-10) */
  exportUrl: (pid: string, rid: string, format: 'csv' | 'parquet', shape: 'long' | 'wide') =>
    `${BASE}/api/v1/projects/${encodeURIComponent(pid)}/radiomics/runs/${encodeURIComponent(rid)}/features?format=${format}&shape=${shape}`,
}
