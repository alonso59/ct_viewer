// Journey G4 (VISION, REL-02; AUD-A6-01) on the real backend: radiomics settings → selection by a
// variable + segmentation set → estimate → run → failures and skips in plain words (items without a
// mask are skipped, not failed) → dashboard → outliers top 10, the injected defect `case_00062` first
// → one click opens it in the viewer → group comparison on a derived variable (p-values) → export.
// TST-05, RAD-05/07/10/11, TSK-04, DB-01/03/10, ANA-04/05, VAR-06; AUD-A2-05, A2-06, A3-04, A3-10,
// A3-15, A3-21, A1-08, A1-18, A5-04 (FB5).
import { readFileSync } from 'node:fs'

import { expect, test, type Page } from '@playwright/test'

import { api, importedProject } from './helpers'

/** A project on the fixtures with a derived grouping variable (VAR-06), set up through the API */
async function project(name: string): Promise<string> {
  const pid = await importedProject(name)
  await expect.poll(async () => (await api<{ variables: { name: string }[] }>('GET', `/projects/${pid}/variables`)).variables.map((v) => v.name), { timeout: 30_000 }).toContain('marker_a')
  await api('POST', `/projects/${pid}/variables/derived`, { op: 'bin', name: 'marker_group', source: 'marker_a', quantiles: [0.5], labels: ['low', 'high'] })
  return pid
}

/** Show a side-bar view (clicking the active view's icon would collapse the side bar) */
async function openSideView(page: Page, name: string, shown: () => Promise<boolean>) {
  if (!(await shown())) await page.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name, exact: true }).click()
}

test('G4: radiomics run, failures in plain words, outliers, viewer, group comparison, export', async ({ page, browserName }) => {
  test.setTimeout(240_000)
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const pid = await project(`G4 ${browserName} ${Date.now()}`)
  await page.goto('/')
  await page.evaluate(() => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: 'Dr. G4' }, version: 0 })))

  // Radiomics settings (RAD-01): the form tab; the bottom panel stays closed on it (AUD-A1-18)
  await page.goto(`/p/${pid}/radiomics`)
  const form = page.locator('.rad')
  await expect(form.getByRole('heading', { name: 'Selection' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('region', { name: 'Panel' })).toHaveCount(0)

  // Selection (RAD-05): filter by a variable (modality = CT) and phase NP, full image, the imported
  // segmentation set, label tumor
  await form.getByRole('radio', { name: 'Filter by variable' }).click()
  await form.locator('.rad-filter .rad-field').filter({ hasText: 'Phase' }).getByRole('checkbox', { name: 'NP', exact: true }).check()
  await form.getByLabel('Variable').selectOption('modality')
  await form.locator('.rad-field').filter({ has: page.locator('.rad-label', { hasText: /^modality$/ }) }).getByRole('checkbox', { name: /^CT/ }).check()
  await form.getByRole('radio', { name: 'Full image' }).click()
  await form.getByLabel('Segmentation set').selectOption('imported')
  const labels = form.locator('.rad-field').filter({ has: page.locator('.rad-label', { hasText: /^Labels$/ }) })
  for (const box of await labels.getByRole('checkbox').all()) await box.uncheck()
  await labels.getByRole('checkbox', { name: /tumor/ }).check()

  // Features: first-order and shape only (keeps the run short)
  await form.getByRole('navigation', { name: 'Setting groups' }).getByRole('button', { name: 'Feature classes' }).click()
  for (const box of await form.locator('.rad-block-row input[type="checkbox"]').all()) {
    const cls = await box.getAttribute('aria-label')
    if (cls === 'firstorder' || cls === 'shape') await box.check()
    else await box.uncheck()
  }

  // Estimate (RAD-11, TSK-04): not-ready items are counted as skipped, with their reasons
  await form.getByRole('button', { name: 'Estimate time' }).click()
  const estimate = form.getByTestId('estimate')
  await expect(estimate).toContainText(/\d+ items × 1 labels = \d+ extractions/, { timeout: 30_000 })
  await expect(estimate).toContainText(/will be skipped \(not ready\): .*no mask/)
  await expect(estimate).toContainText('mask does not line up with the image')
  const name = `G4 run ${browserName}`
  await form.getByLabel('Run name').fill(name)
  await form.getByRole('button', { name: 'Run extraction' }).click()
  await expect(page.getByRole('status').filter({ hasText: `Run “${name}” started` })).toBeVisible()

  // Radiomics view (AUD-A3-21): the run row with the shared status vocabulary (AUD-A3-10)
  const runs = page.getByRole('list', { name: 'Runs' })
  await openSideView(page, 'Radiomics', () => runs.isVisible())
  const runRow = runs.getByRole('listitem').filter({ hasText: name })
  await expect(runRow.locator('.badge[data-status]')).toHaveText('Completed', { timeout: 120_000 })
  await expect(runRow).not.toContainText(/\d+ failed/)
  await expect(runRow).toContainText(/\d+ skipped/)

  // Failures and skips (RAD-07, AUD-A2-05): no failure; skips name the cause in plain words
  await runRow.getByRole('button', { name: 'Failures and skips' }).click()
  const dialog = page.getByRole('dialog', { name: /Failures and skips/ })
  const rows = dialog.locator('tbody tr')
  await expect(rows.first()).toBeVisible()
  await expect(dialog.locator('tbody tr[data-kind="failed"]')).toHaveCount(0)
  await expect(dialog.locator('tr', { hasText: 'case_00013' })).toContainText('The item has no mask.')
  await expect(dialog.locator('tr', { hasText: 'case_00016' })).toContainText('does not line up with the image')
  await expect(dialog).not.toContainText('geometryTolerance')
  await page.keyboard.press('Escape')

  // Dashboard (DB-01): the overview counts skipped items apart from failures
  await runRow.getByRole('button', { name: 'Open dashboard' }).click()
  await expect(page).toHaveURL(/\/run\//)
  await page.getByRole('tab', { name: 'Run overview', exact: true }).click()
  const overview = page.locator('.db-overview')
  await expect(overview).toBeVisible({ timeout: 30_000 })
  const kpi = (label: string) => overview.locator('.kpis > div', { has: page.locator('.muted', { hasText: new RegExp(`^${label}$`) }) }).locator('.kpi')
  await expect(kpi('failed')).toHaveText('0')
  await expect(kpi('skipped')).not.toHaveText('0')

  // Outliers (AUD-A2-06, DB-10): flagged = ≥ 5 % of the features over |z| 3.5 (both adjustable);
  // top 10, sorted by features over the threshold; the injected defect first
  await page.getByRole('tab', { name: 'Outliers', exact: true }).click()
  const table = page.getByRole('table', { name: 'Outliers' })
  await expect(page.getByRole('spinbutton', { name: /Min\. features/ })).toHaveValue('5')
  await expect(table.locator('tbody tr').first()).toContainText('case_00062', { timeout: 30_000 })
  const n = await table.locator('tbody tr').count()
  expect(n).toBeLessThanOrEqual(10)
  const counts = await table.locator('tbody tr td:nth-child(3)').allInnerTexts()
  expect(counts.map(Number)).toEqual([...counts.map(Number)].sort((a, b) => b - a))
  // A3-04 / A3-15: a point as the decimal separator, no thousands separator in values
  for (const v of await table.locator('tbody tr td:nth-child(6)').allInnerTexts()) expect(v).not.toMatch(/\d,\d/)
  const flagged = Number(/^(\d+) of/.exec((await page.getByTestId('outliers-flagged').innerText()) ?? '')?.[1] ?? 0)
  if (flagged > 10) {
    await page.getByRole('button', { name: `Show all ${flagged}` }).click()
    await expect(table.locator('tbody tr')).toHaveCount(flagged)
    await page.getByRole('button', { name: 'Show the top 10' }).click()
  }

  // One click opens the item in the viewer (DB-03)
  await table.locator('tbody tr').first().click()
  await expect(page).toHaveURL(new RegExp(`/p/${pid}/case/case_00062`))
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })

  // Group comparison on the derived variable (ANA-04/05): a test and p-values for the features
  await page.getByRole('tab', { name, exact: true }).click()
  await page.getByRole('tab', { name: 'Group comparison', exact: true }).click()
  const gc = page.locator('.db-view').filter({ has: page.getByLabel('Grouping variable') })
  await gc.getByLabel('Grouping variable').selectOption('marker_group')
  const results = gc.locator('.db-split-side table tbody tr')
  await expect(results.first()).toBeVisible({ timeout: 30_000 })
  const ps = await results.locator('td:nth-child(4)').allInnerTexts()
  expect(ps.length).toBeGreaterThan(5)
  expect(ps.filter((p) => /^\d/.test(p)).length).toBeGreaterThan(5)

  // Export (RAD-10, PHS-03): the wide CSV with the effective phase and the phase at run time
  await openSideView(page, 'Radiomics', () => runs.isVisible())
  const [download] = await Promise.all([page.waitForEvent('download'), runRow.getByRole('link', { name: 'Export CSV (wide)' }).click()])
  const csv = readFileSync(await download.path(), 'utf8')
  const header = csv.split('\n')[0] ?? ''
  expect(header).toContain('phase_at_run')
  expect(header).toContain('original_firstorder_Mean')
  expect(csv).toContain('case_00062')
  expect(csv).not.toContain('case_00013')
  expect(errors).toEqual([])
})
