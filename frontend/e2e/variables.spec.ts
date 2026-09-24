// ROADMAP P6: Variables view end to end against the real API-16..18 on the synthetic fixtures
// (TST-11 variables cohort). The project is created and imported through the API to save time.
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8011}/api/v1`
const dataset = resolve(dirname(fileURLToPath(import.meta.url)), '../../.fixtures/synthetic/Dataset900')

async function importedProject(request: APIRequestContext, name: string): Promise<string> {
  const p = await (await request.post(`${API}/projects`, { data: { name, preset: 'ccrcc' } })).json()
  const pid = p.project_id as string
  const preview = await (await request.post(`${API}/projects/${pid}/imports/preview`, { data: { root: dataset, alias: 'DATA', detect: true } })).json()
  expect((await request.post(`${API}/projects/${pid}/imports`, { data: { preview_id: preview.preview_id } })).status()).toBe(202)
  await expect
    .poll(async () => (await (await request.get(`${API}/projects/${pid}/imports`)).json()).index.state, { timeout: 30_000 })
    .toBe('ready')
  return pid
}

const section = (page: Page, name: string) => page.getByRole('listitem', { name })
const row = (page: Page, name: string) => page.locator('.var-item').filter({ has: page.locator('.var-name .mono', { hasText: new RegExp(`^${name}$`) }) })

test('variables view on the real API: review, overrides, derived, external', async ({ page, request, browserName }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const pid = await importedProject(request, `E2E variables ${browserName} ${Date.now()}`)

  await page.goto(`/p/${pid}`)
  await page.getByRole('navigation', { name: /Activity bar/i }).getByRole('button', { name: 'Variables' }).click()

  // VAR-04: study labels surface without the app knowing their names; no `group`; Acquisition collapsed
  const study = section(page, 'Study')
  for (const n of ['patient_sex', 'patient_age', 'grade', 'marker_a', 'marker_b', 'score']) await expect(row(page, n)).toBeVisible()
  await expect(study.locator('.var-name .mono', { hasText: /^group$/ })).toHaveCount(0)
  const acq = section(page, 'Acquisition')
  await expect(acq.getByRole('button', { name: /Acquisition/ })).toHaveAttribute('aria-expanded', 'false')
  await expect(acq.locator('.var-item')).toHaveCount(0)

  // VAR-03: numeric-discrete → Review badge; confirming the type clears it (PATCH API-16)
  const grade = row(page, 'grade')
  await expect(grade.getByText('Review', { exact: true })).toBeVisible()
  await grade.locator('.var-name').click()
  await grade.getByRole('button', { name: 'Use categorical' }).click()
  await expect(grade.getByText('Review', { exact: true })).toHaveCount(0)
  await expect(grade.getByRole('combobox', { name: /Type of grade/ })).toHaveValue('categorical')
  // Categorical levels come from the profile (`top`)
  await expect(grade.getByLabel('Levels')).toContainText('2')

  // Continuous fields show examples and a range, not levels
  const score = row(page, 'score')
  await score.locator('.var-name').click()
  await expect(score.getByLabel('Levels')).toHaveCount(0)
  await expect(score.locator('.var-examples')).toBeVisible()
  await score.locator('.var-name').click()

  // VAR-05: visibility and a tag
  const marker = row(page, 'marker_b')
  await marker.getByRole('button', { name: /Hide marker_b/ }).click()
  await expect(marker.getByRole('button', { name: /Show marker_b/ })).toBeVisible()
  await marker.locator('.var-name').click()
  const confounder = marker.getByRole('group', { name: 'Tags' }).getByRole('button', { name: /confounder/i })
  await confounder.click()
  await expect(confounder).toHaveAttribute('aria-pressed', 'true')

  // VAR-06: derived bin by thresholds and by quantile groups (group count ↔ cut probabilities)
  const newDerived = async (name: string, mode: 'thresholds' | 'quantiles', value: string) => {
    await page.getByRole('button', { name: /New derived variable/ }).first().click()
    const dlg = page.getByRole('dialog')
    await dlg.getByLabel('Name').fill(name)
    await dlg.getByLabel('Source variable').selectOption('score')
    if (mode === 'quantiles') {
      await dlg.getByRole('button', { name: 'Quantiles', exact: true }).click()
      await dlg.getByLabel('Number of quantiles').fill(value)
    } else await dlg.getByRole('textbox', { name: 'Thresholds' }).fill(value)
    await dlg.getByRole('button', { name: 'Create' }).click()
    await expect(dlg).toBeHidden()
  }
  await newDerived('score_hi', 'thresholds', '50')
  await newDerived('score_q3', 'quantiles', '3')
  const derived = section(page, 'Derived')
  await expect(row(page, 'score_hi')).toBeVisible()
  const q3 = row(page, 'score_q3')
  await q3.locator('.var-name').click()
  await expect(q3.locator('dd.mono')).toContainText('3')
  await expect(q3.getByLabel('Levels').locator('.badge')).toHaveCount(3)
  // A derived variable used by another cannot be deleted: the 422 detail is shown
  await page.getByRole('button', { name: /New derived variable/ }).first().click()
  const rdlg = page.getByRole('dialog')
  await rdlg.getByLabel('Name').fill('score_q3_merged')
  await rdlg.getByRole('radio', { name: 'Recode' }).click()
  await rdlg.getByLabel('Source variable').selectOption('score_q3')
  await rdlg.getByRole('textbox', { name: /Q1/ }).fill('Q1-2')
  await rdlg.getByRole('textbox', { name: /Q2/ }).fill('Q1-2')
  await rdlg.getByRole('button', { name: 'Create' }).click()
  await expect(rdlg).toBeHidden()
  await q3.getByRole('button', { name: /Delete derived variable/ }).click()
  await expect(page.getByRole('status').filter({ hasText: /used by score_q3_merged/ })).toBeVisible()
  await expect(q3).toBeVisible()

  // Delete one derived variable (API-17 DELETE returns the catalog)
  const hi = row(page, 'score_hi')
  await hi.locator('.var-name').click()
  await hi.getByRole('button', { name: /Delete derived variable/ }).click()
  await expect(hi).toHaveCount(0)
  await expect(derived.locator('.var-item')).toHaveCount(2)

  // VAR-07: external table keyed by case_id, one unmatched key
  await page.getByRole('button', { name: 'Import variable table…' }).first().click()
  const dlg = page.getByRole('dialog')
  await dlg.locator('input[type=file]').setInputFiles({
    name: 'extra.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('case_id,biomarker_x,site_x,score\ncase_00001,1.5,A,1\ncase_00002,2.5,B,2\ncase_99999,3,C,3\ncase_00001,9,Z,4\n'),
  })
  await dlg.getByRole('button', { name: 'Import', exact: true }).click()
  const report = dlg.getByRole('status')
  await expect(report).toContainText('2 of 4 rows matched')
  await expect(report).toContainText('Added: biomarker_x, site_x')
  await expect(report).toContainText('case_99999')
  await expect(report).toContainText('1 duplicate key (first row kept): case_00001')
  await expect(report).toContainText('Skipped, name already taken: score')
  await dlg.getByRole('button', { name: 'Close' }).first().click()
  await expect(row(page, 'site_x')).toBeVisible()

  // VAR-10: the derived variable is offered as an explorer column / colour
  await page.getByRole('navigation', { name: /Activity bar/i }).getByRole('button', { name: 'Project' }).click()
  await page.getByRole('button', { name: 'Columns and colour' }).click()
  await expect(page.getByRole('menuitemcheckbox', { name: 'score_q3', exact: true })).toBeVisible()
  await expect(page.getByRole('menuitemradio', { name: 'score_q3', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')

  expect(errors).toEqual([])
})
