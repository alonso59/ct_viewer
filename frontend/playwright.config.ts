import { existsSync, mkdtempSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

// E2E (TST-05/08) against the real backend on the synthetic fixtures (`make fixtures` first).
// Not part of `make check`; run with `make e2e`. Ports avoid the lane dev servers (5173/8000/8010).
const here = dirname(fileURLToPath(import.meta.url))
const backend = resolve(here, '../backend')
const fixtures = resolve(here, '../.fixtures/synthetic')
// Ports can be overridden so two lanes/agents can run E2E side by side
const API_PORT = Number(process.env.E2E_API_PORT ?? 8011)
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5174)
// Fresh workspace per run (workers re-evaluate this file, so the path is passed on via env)
const workspace = process.env.E2E_WORKSPACE ?? mkdtempSync(join(tmpdir(), 'rw-e2e-'))
process.env.E2E_WORKSPACE = workspace
// Writable derived root for task outputs (OPS-11); never inside the fixtures (OPS-12)
const derived = process.env.E2E_DERIVED ?? mkdtempSync(join(tmpdir(), 'rw-e2e-derived-'))
process.env.E2E_DERIVED = derived
// External manifests (TSK-01): the CI plugin only, never `plugins/` itself (TESTING.md)
const plugins = process.env.E2E_PLUGINS ?? mkdtempSync(join(tmpdir(), 'rw-e2e-plugins-'))
process.env.E2E_PLUGINS = plugins
if (!existsSync(join(plugins, 'threshold'))) symlinkSync(resolve(here, '../plugins/threshold'), join(plugins, 'threshold'))

/** Single-quote for the shell: the repo path may contain spaces */
const q = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`

export default defineConfig({
  testDir: './e2e',
  // TST-07 (R1): fixture sources must be byte-identical after the suite
  globalSetup: './e2e/tst07.ts',
  globalTeardown: './e2e/tst07-teardown.ts',
  timeout: 60_000,
  // One backend workspace shared by all tests: run serially
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: 'retain-on-failure' },
  webServer: [
    {
      command:
        `cd ${q(backend)} && WORKSPACE_ROOT=${q(workspace)} ALLOWED_DATA_ROOTS=${q(fixtures)} ALLOWED_DERIVED_ROOTS=${q(derived)} PLUGINS_ROOT=${q(plugins)} ` +
        `PUBLIC_BASE_URL=http://127.0.0.1:${WEB_PORT} .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `VITE_PORT=${WEB_PORT} VITE_API_PROXY=http://127.0.0.1:${API_PORT} npm run dev`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
  ],
})
