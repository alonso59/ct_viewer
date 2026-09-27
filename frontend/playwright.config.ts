import { defineConfig, devices } from '@playwright/test'

import { REUSE, serverCommands, WEB_PORT } from './e2e/servers'

// E2E (TST-05/08) against the real backend on the synthetic fixtures (`make fixtures` first).
// Not part of `make check`; run with `make e2e` (both browsers) or `make e2e-one SPEC=… PROJECT=…`.
// Ports avoid the lane dev servers (5173/8000/8010) and can be overridden (E2E_API_PORT,
// E2E_WEB_PORT) so two lanes/agents run side by side. E2E_REUSE=1 uses servers already running
// (`make e2e-servers`); E2E_BUILD=1 serves the production build; E2E_KEEP=1 keeps the temp folders.
export default defineConfig({
  testDir: './e2e',
  // TST-07 (R1): fixture sources must be byte-identical after the suite; then the temp folders go
  globalSetup: './e2e/tst07.ts',
  globalTeardown: './e2e/tst07-teardown.ts',
  timeout: 60_000,
  // One backend workspace shared by all tests: run serially
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: 'retain-on-failure' },
  webServer: serverCommands().map(({ command, url }) => ({ command, url, reuseExistingServer: REUSE, timeout: 120_000 })),
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
  ],
})
