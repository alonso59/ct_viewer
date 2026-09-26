// AUD-A5-09 / AUD-A6-02 (CUR-08, API-20): the Explorer / Search filters bind to documented API-20
// query parameters, and the Status filter is the case rollup (`curation_status`), not the item status.
import { afterEach, expect, test, vi } from 'vitest'

import { httpApi } from './http'
// the tracked contract snapshot (tests/openapi.snapshot.json); src/api/openapi.json is generated
import openapi from '../../../backend/tests/openapi.snapshot.json'
import { CASE_ROLLUPS } from './types'

interface Param { name: string; in: string; schema?: { anyOf?: { enum?: string[] }[]; enum?: string[] } }
const op = (openapi as unknown as { paths: Record<string, { get: { parameters: Param[] } }> }).paths['/api/v1/projects/{pid}/cases']!.get
const query = new Map(op.parameters.filter((p) => p.in === 'query').map((p) => [p.name, p]))

afterEach(() => vi.unstubAllGlobals())

test('every Search filter is an API-20 query parameter; Status is the CUR-08 rollup', async () => {
  const fetch = vi.fn<(url: string) => Promise<Response>>(async () => new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200, headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal('fetch', fetch)
  await httpApi.listCases('p1', { q: 'case', phase: 'NP', status: 'partially_reviewed', voi: 'any', vars: { age: '40..60' } })
  const url = new URL(String(fetch.mock.calls[0]?.[0]), 'http://x')
  for (const name of url.searchParams.keys()) if (!name.startsWith('var.')) expect(query.has(name), name).toBe(true)
  expect(url.searchParams.get('curation_status')).toBe('partially_reviewed')
  expect(url.searchParams.has('status')).toBe(false)
  const allowed = query.get('curation_status')?.schema?.anyOf?.flatMap((s) => s.enum ?? []) ?? []
  expect([...allowed].sort()).toEqual([...CASE_ROLLUPS].sort())
})
