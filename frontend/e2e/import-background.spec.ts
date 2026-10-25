// U08/B04, SRC-19: preserve import discovery and its project/alias across reload/cancel/resume.
import { spawn } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { expect, test } from '@playwright/test'

import { api } from './helpers'
import { continueImportInspection, continueImportPreview } from './importMode'
import { stopProcess } from './processes'

test('import inspection reloads, cancels and resumes with its original project and alias', async ({ page }) => {
  test.setTimeout(120_000)
  const project = await api<{ project_id: string }>('POST', '/projects', { name: `Import recovery ${Date.now()}` })
  const path = join(process.env.E2E_WORKSPACE!, 'plugins/dicom/execution.lock')
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 })
  const locker = spawn('python3', ['-c', 'import fcntl,sys; f=open(sys.argv[1],"a+"); fcntl.flock(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.read()', path], { stdio: ['pipe', 'pipe', 'pipe'] })
  try {
    await new Promise<void>((resolve, reject) => {
      locker.once('error', reject)
      locker.once('exit', (code) => reject(new Error(`Owned queue lock exited: ${code}`)))
      locker.stdout.once('data', () => resolve())
    })
    await page.goto(`/p/${project.project_id}`)
    await page.keyboard.press('ControlOrMeta+Shift+p')
    await page.getByRole('dialog').getByRole('combobox').fill('Import data')
    await page.getByRole('dialog').getByRole('option', { name: /Import data/ }).click()
    const wizard = page.getByRole('dialog', { name: 'Import data' })
    const folders = wizard.getByRole('listbox', { name: 'Folders' })
    await folders.getByRole('button', { name: /synthetic/ }).click()
    await folders.getByRole('button', { name: /^Dataset900(?: metadata.jsonl)?$/ }).click()
    await wizard.locator('#import-alias-help').locator('..').locator('input').fill('IMAGES')
    const created = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/v1/source-operations'))
    await wizard.getByRole('button', { name: 'Next', exact: true }).click()
    const response = await created
    expect(response.status()).toBe(202)
    const operation = await response.json() as { operation_id: string; attempt: number; project_id: string }
    expect(operation.project_id).toBe(project.project_id)
    const inspection = page.getByRole('dialog', { name: 'Inspect import source' })
    await inspection.getByRole('button', { name: 'Minimize', exact: true }).first().click()
    await page.reload()
    const chip = page.getByTestId('conv-chip')
    await expect(chip).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await chip.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect.poll(async () => (await api<{ status: string }>('GET', `/source-operations/${operation.operation_id}`)).status).toBe('cancelled')
    await chip.getByRole('button', { name: 'Show', exact: true }).click()
    await inspection.getByRole('button', { name: 'Resume pending work', exact: true }).click()
    await expect.poll(async () => (await api<{ attempt: number }>('GET', `/source-operations/${operation.operation_id}`)).attempt).toBe(operation.attempt + 1)
    locker.stdin.end()
    await stopProcess(locker)
    await continueImportInspection(page)
    await expect(wizard.getByRole('radio', { name: /Metadata table/ })).toBeChecked()
    const preview = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/import-preview'))
    await wizard.getByRole('button', { name: 'Next', exact: true }).click()
    const result = await preview
    expect(result.status()).toBe(202)
    await continueImportPreview(page)
    await expect(wizard.getByRole('button', { name: 'Import and index', exact: true })).toBeVisible()
    const restored = await api<{ import_context: { alias: string }; conversion_run_id: string | null }>('GET', `/source-operations/${operation.operation_id}`)
    expect(restored.import_context.alias).toBe('IMAGES')
    expect(restored.conversion_run_id).toBeNull()
    await expect(page).toHaveURL(new RegExp(`/p/${project.project_id}$`))
  } finally {
    locker.stdin.end()
    await stopProcess(locker)
  }
})
