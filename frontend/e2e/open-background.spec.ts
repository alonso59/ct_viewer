// U08/B04, SRC-18/UI-28: real background Open survives minimize/reload/cancel/resume.
// A test-owned flock holds only this disposable workspace's DICOM dispatch queue.
import { spawn } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { expect, test } from '@playwright/test'

import { api, DATASET } from './helpers'
import { openViaHistoryState } from './openMode'
import { stopProcess } from './processes'

test('minimized source opening reloads, cancels and resumes the same operation', async ({ page }) => {
  test.setTimeout(120_000)
  const path = join(process.env.E2E_WORKSPACE!, 'plugins/dicom/execution.lock')
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 })
  const locker = spawn('python3', ['-c', 'import fcntl,sys; f=open(sys.argv[1],"a+"); fcntl.flock(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.read()', path], { stdio: ['pipe', 'pipe', 'pipe'] })
  try {
    await new Promise<void>((resolve, reject) => {
      locker.once('error', reject)
      locker.once('exit', (code) => reject(new Error(`Owned queue lock exited: ${code}`)))
      locker.stdout.once('data', () => resolve())
    })
    await page.goto('/')
    const created = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/v1/source-operations'))
    await openViaHistoryState(page, `${DATASET}/nifti`)
    const response = await created
    expect(response.status()).toBe(202)
    const operation = await response.json() as { operation_id: string; attempt: number }
    let window = page.getByRole('dialog', { name: 'Open file or folder', exact: true })
    await expect(window).toBeVisible()
    await window.getByRole('button', { name: 'Minimize', exact: true }).first().click()
    const chip = page.getByTestId('conv-chip')
    await expect(chip).toBeVisible()
    await page.reload()
    await expect(chip).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(chip.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible()
    await chip.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect.poll(async () => (await api<{ status: string }>('GET', `/source-operations/${operation.operation_id}`)).status).toBe('cancelled')
    await chip.getByRole('button', { name: 'Show', exact: true }).click()
    window = page.getByRole('dialog', { name: 'Open file or folder', exact: true })
    await window.getByRole('button', { name: 'Resume pending work', exact: true }).click()
    await expect.poll(async () => (await api<{ attempt: number }>('GET', `/source-operations/${operation.operation_id}`)).attempt).toBe(operation.attempt + 1)
    locker.stdin.end()
    await stopProcess(locker)
    await window.getByRole('button', { name: 'Open in viewer', exact: true }).click({ timeout: 30_000 })
    await expect(page).toHaveURL(new RegExp(`/open/${operation.operation_id}$`))
    await expect(page.locator('.vp').first()).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
    const completed = await api<{ purpose: string; stage: string; conversion_run_id: string | null }>('GET', `/source-operations/${operation.operation_id}`)
    expect(completed).toMatchObject({ purpose: 'open', stage: 'opened', conversion_run_id: null })
  } finally {
    locker.stdin.end()
    await stopProcess(locker)
  }
})
