// E2E servers and temp folders (TST-05, AUD-A6-18, AUD-A0-05), shared by playwright.config.ts and
// `e2e/serve.ts` (`make e2e-servers`). The folders are passed on through the environment, since
// Playwright workers evaluate the config again.
import { existsSync, mkdirSync, mkdtempSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const here = import.meta.dirname
const backend = resolve(here, '../../backend')
export const fixtures = resolve(here, '../../.fixtures/synthetic')
export const API_PORT = Number(process.env.E2E_API_PORT ?? 8011)
export const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5174)
/** `E2E_REUSE=1`: use servers that already run on the ports (`make e2e-servers`), fixed folders */
export const REUSE = !!process.env.E2E_REUSE
/** `E2E_BUILD=1`: serve the production build (`vite preview`) instead of the dev server */
const BUILD = !!process.env.E2E_BUILD

const KEYS = [
  ['E2E_WORKSPACE', 'rw-e2e-'],
  ['E2E_DERIVED', 'rw-e2e-derived-'],
  ['E2E_PLUGINS', 'rw-e2e-plugins-'],
] as const

/** Workspace, derived and plugins folders; fresh temp folders unless given or reused */
export function e2eDirs(): { workspace: string; derived: string; plugins: string } {
  const created: string[] = JSON.parse(process.env.E2E_CREATED ?? '[]')
  for (const [key, prefix] of KEYS) {
    if (process.env[key]) continue
    let dir: string
    if (REUSE) {
      // the same folders every time, so a second run matches the servers of the first
      dir = join(tmpdir(), 'rw-e2e-reuse', prefix.replace(/-$/, ''))
      mkdirSync(dir, { recursive: true })
    } else {
      dir = mkdtempSync(join(tmpdir(), prefix))
      created.push(dir)
    }
    process.env[key] = dir
  }
  process.env.E2E_CREATED = JSON.stringify(created)
  const plugins = process.env.E2E_PLUGINS!
  // External manifests (TSK-01): the CI plugin only, never `plugins/` itself (TESTING.md)
  if (!existsSync(join(plugins, 'threshold'))) symlinkSync(resolve(here, '../../plugins/threshold'), join(plugins, 'threshold'))
  return { workspace: process.env.E2E_WORKSPACE!, derived: process.env.E2E_DERIVED!, plugins }
}

/** Folders this run created (removed by the global teardown unless `E2E_KEEP` is set) */
export const createdDirs = (): string[] => JSON.parse(process.env.E2E_CREATED ?? '[]')

/** Single-quote for the shell: the repo path may contain spaces */
const q = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`

export function serverCommands(d = e2eDirs()) {
  const web = BUILD
    ? `npx vite build --outDir .vite/e2e-dist --emptyOutDir --logLevel error && npx vite preview --outDir .vite/e2e-dist --port ${WEB_PORT} --strictPort`
    : 'npm run dev'
  return [
    {
      name: 'api',
      command:
        `cd ${q(backend)} && WORKSPACE_ROOT=${q(d.workspace)} ALLOWED_DATA_ROOTS=${q(fixtures)} ALLOWED_DERIVED_ROOTS=${q(d.derived)} PLUGINS_ROOT=${q(d.plugins)} ` +
        `PUBLIC_BASE_URL=http://127.0.0.1:${WEB_PORT} .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
    },
    {
      name: 'web',
      command: `VITE_PORT=${WEB_PORT} VITE_API_PROXY=http://127.0.0.1:${API_PORT} ${web}`,
      url: `http://127.0.0.1:${WEB_PORT}`,
    },
  ]
}
