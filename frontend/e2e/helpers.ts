// Shared E2E helpers (TST-05, AUD-A6-17): the API through the web server's proxy (the `baseURL`
// the pages use), the fixture paths, and one imported project on the synthetic dataset.
import { resolve } from 'node:path'

import { expect } from '@playwright/test'

/** The app origin (Vite dev server or a reused one, playwright.config.ts) */
export const WEB = `http://127.0.0.1:${process.env.E2E_WEB_PORT ?? 5174}`
export const API = `${WEB}/api/v1`
export const FIXTURES = resolve(import.meta.dirname, '../../.fixtures/synthetic')
export const DATASET = `${FIXTURES}/Dataset900`

/** JSON request to the API; `X-Reviewer: E2E` unless `headers` says otherwise; 204 → null */
export async function api<T = unknown>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method,
    headers: { 'content-type': 'application/json', 'X-Reviewer': 'E2E', ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`)
  return (r.status === 204 ? null : await r.json()) as T
}

/** A new project with the ccRCC pack and the synthetic dataset imported and indexed (IMP-*) */
export async function importedProject(name: string, { packs = ['ccrcc'], root = DATASET }: { packs?: string[]; root?: string } = {}): Promise<string> {
  const { project_id: pid } = await api<{ project_id: string }>('POST', '/projects', { name, packs })
  const pv = await api<{ preview_id: string }>('POST', `/projects/${pid}/imports/preview`, { root, alias: 'DATA', detect: true })
  await api('POST', `/projects/${pid}/imports`, { preview_id: pv.preview_id })
  await expect.poll(async () => (await api<{ index: { state: string } }>('GET', `/projects/${pid}/imports`)).index.state, { timeout: 30_000 }).toBe('ready')
  return pid
}
