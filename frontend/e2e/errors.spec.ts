// UI-18, FE-09 on the real backend: a project that cannot load is a problem card with Try again and
// Workspace home, never an endless "Loading…"; an unreachable server and a server error both get
// one, and Try again recovers once the server answers. Without WebGL2 the viewer says what to do
// and offers a reload.
import { expect, test } from '@playwright/test'

import { FIXTURES, importedProject } from './helpers'
import { gotoOpen } from './openMode'

test('a project load failure is a card with actions; Try again recovers', async ({ page }) => {
  const pid = await importedProject(`errors ${Date.now()}`)
  let mode: 'abort' | 'error' | 'pass' = 'abort'
  await page.route(new RegExp(`/api/v1/projects/${pid}$`), (route) => {
    if (mode === 'abort') return route.abort()
    if (mode === 'error') return route.fulfill({ status: 500, contentType: 'application/problem+json', body: JSON.stringify({ type: 'about:blank', title: 'Internal Server Error', status: 500, detail: 'Injected by the test' }) })
    return route.continue()
  })
  await page.goto(`/p/${pid}`)
  const offline = page.getByRole('alert').filter({ hasText: 'Cannot reach the server' })
  await expect(offline).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('link', { name: 'Workspace home' })).toBeVisible()
  await expect(page).not.toHaveTitle(/Loading/)
  mode = 'error'
  await offline.getByRole('button', { name: 'Try again' }).click()
  const failed = page.getByRole('alert').filter({ hasText: 'Injected by the test' })
  await expect(failed.getByRole('button', { name: 'Try again' })).toBeVisible({ timeout: 30_000 })
  mode = 'pass'
  await failed.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('tree', { name: 'Explorer' })).toBeVisible({ timeout: 30_000 })
})

test('without WebGL2 the viewer says what to do and offers a reload', async ({ page }) => {
  // e2e has no DOM lib: the page script is a string
  await page.addInitScript(`(() => {
    const get = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function (type, ...rest) { return type === 'webgl2' ? null : get.call(this, type, ...rest) }
  })()`)
  await gotoOpen(page, `${FIXTURES}/Dataset900/nifti/04_case_00002_0000.nii.gz`)
  const card = page.getByRole('alert').filter({ hasText: 'WebGL2' })
  await expect(card).toBeVisible({ timeout: 30_000 })
  await expect(card.getByRole('button', { name: 'Reload app' })).toBeVisible()
})
