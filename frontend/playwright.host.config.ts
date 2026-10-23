// Explicit host-only lane: actual user services and sandbox, synthetic GPU accounting, CPU task.
import { defineConfig, devices } from '@playwright/test'

if (!process.env.RW_BROWSER_ACCEPTANCE) throw new Error('Run backend tools.runner_browser_acceptance')

export default defineConfig({
  testDir: './host-e2e',
  workers: 1,
  timeout: 120_000,
  use: { baseURL: process.env.RW_HOST_URL, trace: 'retain-on-failure' },
  outputDir: '../build/verification/supervised-browser',
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'], headless: false, launchOptions: { firefoxUserPrefs: { 'webgl.force-enabled': true } } } },
  ],
})
