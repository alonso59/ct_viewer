// ROADMAP P2 exit: create a project, import data, browse cases, share a link that opens in a
// second browser. Real backend on the synthetic fixtures (TST-11); see playwright.config.ts.
import { expect, test, type Page } from '@playwright/test'

const collectErrors = (page: Page) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  return errors
}

test('new project → import → browse → share link', async ({ page, browser, browserName }) => {
  const errors = collectErrors(page)
  const name = `E2E ${browserName} ${Date.now()}`

  // Workspace home → New project (default preset ccRCC)
  await page.goto('/')
  await page.getByRole('button', { name: /New project/ }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Project name').fill(name)
  await expect(dialog.getByRole('radio', { name: /ccRCC/ })).toBeChecked()
  await dialog.getByRole('button', { name: 'Create and import' }).click()

  // Import wizard on /p/{pid}
  await expect(page).toHaveURL(/\/p\/[0-9A-Z]{26}/)
  const pid = /\/p\/([0-9A-Z]{26})/.exec(page.url())?.[1] ?? ''
  const wizard = page.getByRole('dialog', { name: 'Import data' })
  await expect(wizard).toBeVisible()
  const folders = wizard.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  const dataset = folders.getByRole('button', { name: /Dataset900/ })
  await expect(dataset).toContainText('metadata.jsonl')
  await dataset.click()
  await wizard.getByRole('button', { name: 'Next' }).click()

  // Detect: the three input files
  for (const f of ['metadata.jsonl', 'phase.json', 'voi_catalog.jsonl']) await expect(wizard.getByRole('cell', { name: f, exact: true })).toBeVisible()
  await wizard.getByRole('button', { name: 'Next' }).click()

  // Preview: counts from the fixtures
  const kpi = (label: string) => wizard.locator('.card', { hasText: label }).locator('.kpi')
  await expect(kpi('cases')).toHaveText('17')
  await expect(kpi('scan rows')).toHaveText('24')
  await wizard.getByRole('button', { name: 'Import and index' }).click()

  // Indexing job → wizard closes with a toast
  await expect(page.getByRole('status').filter({ hasText: 'Import finished' })).toBeVisible({ timeout: 30_000 })
  await expect(wizard).toBeHidden()

  // Browse: Project view lists cases; open case_00001
  const tree = page.getByRole('tree', { name: 'Project' })
  const row = tree.getByRole('treeitem', { name: /case_00001/ })
  await expect(row).toBeVisible()
  await row.dblclick()
  await expect(page).toHaveURL(new RegExp(`/p/${pid}/case/case_00001`))

  // Problems panel lists the fixture warnings
  await page.getByRole('tab', { name: /Problems/ }).click()
  await expect(page.getByRole('tabpanel').getByRole('treeitem').filter({ hasText: 'case_00010' }).first()).toBeVisible()

  // SSE connected
  const status = page.getByRole('contentinfo', { name: 'Status bar' })
  await expect(status.getByText('live', { exact: true })).toBeVisible()

  // Share link: the toast carries the URL whether or not the clipboard is available
  await page.getByRole('button', { name: 'Copy share link' }).click()
  const toast = page.getByRole('status').filter({ hasText: /Share link copied|Copy this link/ })
  await expect(toast).toBeVisible()
  const url = /(https?:\/\/\S+)/.exec((await toast.textContent()) ?? '')?.[1] ?? ''
  expect(url).toContain(`/p/${pid}/case/case_00001`)

  // Second browser: same project and case
  const other = await browser.newContext()
  const page2 = await other.newPage()
  const errors2 = collectErrors(page2)
  await page2.goto(url)
  await expect(page2.getByRole('button', { name: 'Switch project' })).toContainText(name)
  await expect(page2).toHaveURL(new RegExp(`/p/${pid}/case/case_00001`))
  await expect(page2.getByRole('tree', { name: 'Project' }).getByRole('treeitem', { name: /case_00001/ })).toBeVisible()
  await other.close()

  expect(errors).toEqual([])
  expect(errors2).toEqual([])
})

test('an unknown share link shows project not found', async ({ page }) => {
  await page.goto('/p/01XXXXXXXXXXXXXXXXXXXXXXXX')
  await expect(page.getByText('Project not found')).toBeVisible()
})
